"""授信助手 Agent 单元测试（P0）。

覆盖：
1. 领域分类短路（无关问题零 LLM / 零工具；纯政策问题引导到政策问答）
2. 三个只读工具：归属校验、数据渲染、状态过滤
3. 工具超时 / 异常降级
4. 引用后处理（业务数据编号、kind=business）
5. Agent 主流程：工具结果 → 答案 → actions / tool_calls
6. LLM 失败时回退为业务数据直出

不依赖 MySQL 与真实 LLM，仓储与 LLM 全部 patch 隔离。
"""

from __future__ import annotations

import time
from decimal import Decimal
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from pydantic import ValidationError

from app.assistant.agent import (
    _agent_prompts,
    _build_actions,
    _detect_product,
    _plan_calls,
    _rule_calls,
    chat,
)
from app.assistant.prompt import (
    PLANNER_SYSTEM_PROMPT,
    outcomes_to_hits,
    truncate_history,
)
from app.assistant.schemas import AssistantRequest, AssistantResponse
from app.assistant.tool_impl import (
    BusinessRef,
    ToolOutcome,
    _get_application_detail,
    _get_owned_app,
    _get_precheck_summary,
    _get_required_materials,
    _list_my_applications,
    _list_my_todos,
    _list_products,
    _preview_eligibility,
    _search_policy,
    execute_tool,
)
from app.assistant.tools import (
    MANAGER_TOOL_NAMES,
    RISK_TOOL_NAMES,
    TOOL_NAMES,
    PlannedCall,
    ToolPlan,
)
from app.core import config
from app.models.application import Application
from app.models.enums import AiConclusion, ApplicationStatus, MaterialStatus, UserRole
from app.models.user import User
from app.qa.schemas import QaMessage, QaRequest, ReferenceItem
from app.qa.service import _is_personal_business_question, ask_question
from app.rag.kb_retriever import KnowledgeHit


def _user(full_name: str = "张三") -> User:
    return User(
        username="mgr_zhangsan",
        full_name=full_name,
        role=UserRole.MANAGER,
        hashed_password="x",
        is_active=True,
    )


def _app(**overrides):
    base = dict(
        id=12,
        app_no="AP20260001",
        company_name="杭州示例科技有限公司",
        credit_code="91330100MA2AB1234X",
        amount=Decimal("120.00"),
        product="普惠小微经营贷",
        status=ApplicationStatus.SUPPLEMENT,
        manager_name="张三",
        supplement_note="补充近 6 个月银行流水",
        supplement_source="manual",
        updated_at=None,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


# ====================================================================
# Schema
# ====================================================================


class TestSchemas:
    def test_request_requires_question(self):
        with pytest.raises(ValidationError):
            AssistantRequest(question="")

    def test_response_confidence_bounds(self):
        with pytest.raises(ValidationError):
            AssistantResponse(answer="ok", confidence=1.5)

    def test_reference_kind_defaults_to_policy(self):
        ref = ReferenceItem(index=1, collection="kb_policy", source="a.md", excerpt="x")
        assert ref.kind == "policy"


# ====================================================================
# 领域分类与短路
# ====================================================================


class TestIntentGate:
    def test_out_of_scope_short_circuit(self):
        with patch("app.assistant.agent._run_tool_rounds") as m_tools, patch(
            "app.assistant.agent.get_client"
        ) as m_llm:
            resp = chat(AssistantRequest(question="帮我写一段 Python 代码"), _user(), db=None)
        assert "只回答与授信业务办理相关" in resp.answer
        assert resp.confidence == 0.0
        m_tools.assert_not_called()
        m_llm.assert_not_called()

    def test_policy_only_uses_search_policy_and_offers_qa(self):
        hit = KnowledgeHit(
            collection="kb_policy",
            text="普惠小微经营贷要求企业成立满 24 个月。",
            score=0.9,
            metadata={"source": "01_信贷政策/准入规则/普惠小微经营贷.md", "rule_id": "AP-H02"},
        )
        outcome = ToolOutcome(name="search_policy", ok=True, policy_hits=[hit])
        question = "普惠小微经营贷对成立年限有什么要求？"
        with patch(
            "app.assistant.agent._run_tool_rounds", return_value=[outcome]
        ), patch("app.assistant.agent.get_client") as m_llm:
            m_llm.return_value.chat.return_value = SimpleNamespace(
                content="要求成立满 24 个月 [1]。", model="mock"
            )
            resp = chat(AssistantRequest(question=question), _user(), db=None)

        assert resp.references[0].kind == "policy"
        assert resp.actions[-1].type == "open_qa"
        assert resp.actions[-1].payload == {"question": question}
        m_llm.assert_called_once()

    def test_business_references_do_not_offer_qa_jump(self):
        outcome = ToolOutcome(
            name="list_my_applications",
            ok=True,
            refs=[BusinessRef("申请 AP20260001", "待补件")],
            apps=[{"id": 12, "app_no": "AP20260001"}],
        )
        references = [
            ReferenceItem(
                index=1,
                kind="business",
                collection="business",
                source="申请 AP20260001",
                excerpt="待补件",
            )
        ]
        actions = _build_actions([outcome], references, "我有几笔待补件？")
        assert [a.type for a in actions] == ["navigate"]

    def test_disabled_short_circuit(self):
        with patch.object(config, "ASSISTANT_ENABLED", False):
            resp = chat(AssistantRequest(question="我有几笔待补件"), _user(), db=None)
        assert "暂未启用" in resp.answer

    def test_app_id_makes_vague_question_in_scope(self):
        outcome = ToolOutcome(
            name="get_application_detail",
            ok=True,
            refs=[BusinessRef("申请 AP20260001", "申请编号：AP20260001")],
            apps=[{"id": 12, "app_no": "AP20260001"}],
        )
        with patch("app.assistant.agent._run_tool_rounds", return_value=[outcome]), patch(
            "app.assistant.agent.get_client"
        ) as m_llm:
            m_llm.return_value.chat.return_value = SimpleNamespace(
                content="该申请处于待补件状态 [1]。", model="mock"
            )
            resp = chat(
                AssistantRequest(question="这是什么情况？", app_id=12), _user(), db=None
            )
        assert resp.answer == "该申请处于待补件状态 [1]。"
        assert resp.actions[0].target == "/detail/12"


# ====================================================================
# 工具实现
# ====================================================================


class TestTools:
    def test_list_applications_isolated_by_manager(self):
        rows = [
            _app(updated_at=None),
            _app(id=13, app_no="AK20260002", product="小微快贷", status=ApplicationStatus.MANUAL),
        ]
        fake_repo = MagicMock()
        fake_repo.list_by_manager.return_value = (rows, 2)

        with patch("app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo):
            text, refs, apps = _list_my_applications(
                None, _user(), {"status": "待补件"}
            )

        fake_repo.list_by_manager.assert_called_once_with(
            "张三",
            status_filter=ApplicationStatus.SUPPLEMENT,
            keyword=None,
            page=1,
            page_size=10,
        )
        assert "你名下共 2 笔申请" in text
        assert "AP20260001" in text and "待补件" in text
        assert len(refs) == 2 and len(apps) == 2

    def test_detail_rejects_other_manager(self):
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = _app(manager_name="李四")
        fake_material = MagicMock()

        with patch("app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo), patch(
            "app.assistant.tool_impl.MaterialRepository", return_value=fake_material
        ):
            text, refs, apps = _get_application_detail(None, _user(), {"app_id": 12})

        assert text.startswith("未找到该申请")
        assert refs == [] and apps == []
        fake_material.list_by_app.assert_not_called()

    def test_detail_masks_credit_code(self):
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = _app()
        fake_material = MagicMock()
        fake_material.list_by_app.return_value = [
            SimpleNamespace(
                category="business_license",
                file_name="license.pdf",
                status=MaterialStatus.OK,
            )
        ]

        with patch("app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo), patch(
            "app.assistant.tool_impl.MaterialRepository", return_value=fake_material
        ):
            text, _, _ = _get_application_detail(None, _user(), {"app_id": 12})

        assert "9133****234X" in text
        assert "91330100MA2AB1234X" not in text
        assert "营业执照 1 份" in text

    def test_precheck_summary_reads_snapshot(self):
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = _app()
        report = SimpleNamespace(
            conclusion=AiConclusion.ATTENTION,
            pass_rate=Decimal("72.50"),
            rule_results={
                "pass_count": 8,
                "total_count": 10,
                "hard_fail_count": 1,
                "soft_fail_count": 1,
                "uncertain_count": 0,
                "level": "B",
                "rules": [
                    {
                        "rule_id": "AP-H03",
                        "rule_name": "成立年限",
                        "result": "fail",
                        "detail": "实际 1 年",
                    }
                ],
            },
            risk_signals=[{"title": "流水覆盖不足", "level": "medium"}],
            conflicts=[{"reason": "企业名称不一致"}],
            completeness={"missing": ["tax_return"]},
        )
        fake_report_repo = MagicMock()
        fake_report_repo.get_latest_by_app.return_value = report

        with patch("app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo), patch(
            "app.assistant.tool_impl.ReportRepository", return_value=fake_report_repo
        ):
            text, refs, apps = _get_precheck_summary(None, _user(), {"app_id": 12})

        assert "风险建议关注" in text
        assert "72.5%" in text
        assert "AP-H03" in text
        assert "流水覆盖不足" in text
        assert "企业名称不一致" in text
        assert "纳税申报表" in text
        assert refs[0].source.startswith("预审报告")

    def test_precheck_summary_without_report(self):
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = _app()
        fake_report_repo = MagicMock()
        fake_report_repo.get_latest_by_app.return_value = None

        with patch("app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo), patch(
            "app.assistant.tool_impl.ReportRepository", return_value=fake_report_repo
        ):
            text, refs, _ = _get_precheck_summary(None, _user(), {"app_id": 12})

        assert "尚未生成 AI 预审报告" in text
        assert len(refs) == 1

    def test_precheck_summary_reuses_shared_constructor(self):
        """列表摘要与助手工具必须共用同一个构造函数与渲染函数。"""
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = _app()
        fake_report_repo = MagicMock()
        fake_report_repo.get_latest_by_app.return_value = SimpleNamespace()

        with patch("app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo), patch(
            "app.assistant.tool_impl.ReportRepository", return_value=fake_report_repo
        ), patch(
            "app.assistant.tool_impl.build_precheck_summary_view", return_value="VIEW"
        ) as m_view, patch(
            "app.assistant.tool_impl.render_precheck_summary_text", return_value="TEXT"
        ) as m_text:
            text, _, _ = _get_precheck_summary(None, _user(), {"app_id": 12})

        m_view.assert_called_once()
        m_text.assert_called_once()
        assert text == "TEXT"

    def test_list_products_reads_rule_configs(self):
        configs = [
            {"product": "普惠小微经营贷", "product_code": "AP"},
            {"product": "小微快贷", "product_code": "AK"},
        ]
        with patch("app.assistant.tool_impl.list_rule_configs", return_value=configs):
            text, refs, apps = _list_products(None, _user(), {})

        assert "普惠小微经营贷" in text and "AP" in text
        assert "小微快贷" in text
        assert len(refs) == 2 and apps == []

    def test_preview_eligibility_rejects_other_manager(self):
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = _app(manager_name="李四")

        with patch("app.assistant.tool_impl.load_rule_config", return_value={"rules": []}), patch(
            "app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo
        ):
            text, refs, apps = _preview_eligibility(
                None, _user(), {"product": "普惠小微经营贷", "app_id": 12}
            )

        assert text.startswith("未找到该申请")
        assert refs == [] and apps == []

    def test_preview_eligibility_from_profile(self):
        rule_item = SimpleNamespace(
            rule_id="AP-H02",
            rule_name="成立年限 ≥ 2 年",
            result="fail",
            expected=">= 24",
            actual="12",
        )
        result = SimpleNamespace(
            score=Decimal("61"),
            level="C",
            pass_count=3,
            total_count=4,
            hard_fail_count=1,
            soft_fail_count=0,
            uncertain_count=0,
            rules=[rule_item],
        )
        with patch(
            "app.assistant.tool_impl.load_rule_config", return_value={"rules": []}
        ), patch("app.assistant.tool_impl.evaluate_rules", return_value=result):
            text, refs, apps = _preview_eligibility(
                None,
                _user(),
                {"product": "普惠小微经营贷", "profile": "年营收 800 万，成立 1 年，申请 100 万"},
            )

        assert "AP-H02" in text and "不符合" in text
        assert "以正式 AI 预审为准" in text
        assert len(refs) == 1 and apps == []

    def test_required_materials_lists_core_categories(self):
        with patch("app.assistant.tool_impl.retrieve_material_hints", return_value={}), patch(
            "app.assistant.tool_impl.extra_required_categories", return_value=[]
        ):
            text, refs, apps = _get_required_materials(
                None, _user(), {"product": "普惠小微经营贷"}
            )

        assert "营业执照" in text and "银行流水" in text and "征信授权书" in text
        assert len(refs) == 1 and apps == []

    def test_search_policy_returns_policy_hits(self):
        hit = KnowledgeHit(
            collection="kb_policy",
            text="成立满 24 个月",
            score=0.88,
            metadata={"source": "01_信贷政策/准入规则/普惠小微经营贷.md"},
        )
        with patch(
            "app.assistant.tool_impl.retrieve_policy_hits",
            return_value=([hit], ["kb_policy"], False),
        ):
            result = _search_policy(None, _user(), {"query": "成立年限要求", "product": "普惠小微经营贷"})

        assert len(result) == 4
        text, _refs, _apps, policy_hits = result
        assert "普惠小微经营贷.md" in text
        assert policy_hits[0].collection == "kb_policy"

    def test_list_my_todos_groups_by_priority(self):
        supplement_row = _app()
        manual_row = _app(
            id=13,
            app_no="AK20260002",
            product="小微快贷",
            status=ApplicationStatus.MANUAL,
            supplement_note=None,
            supplement_source=None,
        )

        def fake_list(manager, *, status_filter=None, keyword=None, page=1, page_size=3):
            if status_filter == ApplicationStatus.SUPPLEMENT:
                return [supplement_row], 2
            if status_filter == ApplicationStatus.MANUAL:
                return [manual_row], 1
            return [], 0

        fake_repo = MagicMock()
        fake_repo.list_by_manager.side_effect = fake_list

        with patch("app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo):
            text, refs, apps = _list_my_todos(None, _user(), {})

        assert "待补件 2 笔" in text and "待人工核验 1 笔" in text
        assert "AP20260001" in text and "AK20260002" in text
        assert len(refs) == 2 and len(apps) == 2
        assert refs[0].source == "申请 AP20260001"

    def test_list_my_todos_empty(self):
        fake_repo = MagicMock()
        fake_repo.list_by_manager.return_value = ([], 0)

        with patch("app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo):
            text, refs, apps = _list_my_todos(None, _user(), {})

        assert "暂无待办" in text
        assert refs == [] and apps == []

    def test_search_policy_empty_index(self):
        with patch(
            "app.assistant.tool_impl.retrieve_policy_hits", return_value=([], [], False)
        ):
            text, refs, apps, policy_hits = _search_policy(
                None, _user(), {"query": "AP-H03 是什么规则"}
            )

        assert "暂未检索到" in text
        assert refs == [] and apps == [] and policy_hits == []

    def test_tool_timeout_discards_result(self):
        def _slow(db, user, args):
            time.sleep(0.2)
            return "late", [], []

        with patch.dict("app.assistant.tool_impl._HANDLERS", {"slow": _slow}):
            outcome = execute_tool("slow", {}, None, _user(), timeout=0.05)

        assert outcome.ok is False
        assert outcome.error == "查询超时"
        assert outcome.refs == []

    def test_tool_exception_downgraded(self):
        def _boom(db, user, args):
            raise RuntimeError("db down")

        with patch.dict("app.assistant.tool_impl._HANDLERS", {"boom": _boom}):
            outcome = execute_tool("boom", {}, None, _user(), timeout=1)

        assert outcome.ok is False
        assert outcome.error == "查询失败"


# ====================================================================
# Prompt / 引用后处理
# ====================================================================


class TestReferences:
    def test_outcomes_to_hits_wraps_business(self):
        outcome = ToolOutcome(
            name="list_my_applications",
            ok=True,
            refs=[BusinessRef("申请 AP20260001", "待补件")],
        )
        hits = outcomes_to_hits([outcome])
        assert hits[0].collection == "business"
        assert hits[0].metadata["source"] == "申请 AP20260001"

    def test_failed_outcome_has_no_hits(self):
        outcome = ToolOutcome(name="get_application_detail", ok=False, error="查询超时")
        assert outcomes_to_hits([outcome]) == []

    def test_truncate_history_keeps_recent_turns(self):
        history = [
            QaMessage(role="user", content=f"q{i}") if i % 2 == 0
            else QaMessage(role="assistant", content=f"a{i}")
            for i in range(10)
        ]
        kept = truncate_history(history, 2)
        assert len(kept) == 4
        assert kept[0]["content"] == "q6"


# ====================================================================
# 政策问答个人化引导（P1）
# ====================================================================


class TestQaPersonalIntent:
    def test_personal_question_hints_assistant_without_retrieval(self):
        with patch.object(config, "QA_ENABLED", True), patch(
            "app.qa.service._retrieve_with_fallback"
        ) as m_retrieve, patch("app.qa.service.get_client") as m_llm:
            resp = ask_question(QaRequest(question="我有几笔待补件？"))

        assert resp.hint and "授信助手" in resp.hint
        assert resp.references == []
        m_retrieve.assert_not_called()
        m_llm.assert_not_called()

    def test_personal_detection_requires_pronoun_and_application_semantics(self):
        assert _is_personal_business_question("我有几笔待补件")
        assert not _is_personal_business_question("我的企业成立 2 年能做什么产品")
        assert not _is_personal_business_question("补件时需要什么材料")


# ====================================================================
# 新建申请预填（P2：只预填，不提交）
# ====================================================================


class TestPrefillNewApp:
    def test_prefill_extracts_three_fields_without_tools(self):
        question = "帮我为杭州示例科技有限公司新建一笔 100 万的普惠小微经营贷"
        with patch("app.assistant.agent._run_tool_rounds") as m_tools, patch(
            "app.assistant.agent.get_client"
        ) as m_llm:
            resp = chat(AssistantRequest(question=question), _user(), db=None)

        assert resp.actions[0].type == "prefill_new_app"
        assert resp.actions[0].payload == {
            "product": "普惠小微经营贷",
            "company_name": "杭州示例科技有限公司",
            "amount": "100",
        }
        assert resp.tool_calls == []
        m_tools.assert_not_called()
        m_llm.assert_not_called()

    def test_no_create_tool_registered(self):
        assert "prefill_new_app" not in TOOL_NAMES
        assert "create_application" not in TOOL_NAMES

    def test_prefill_without_fields_asks_for_info(self):
        with patch("app.assistant.agent._run_tool_rounds") as m_tools:
            resp = chat(AssistantRequest(question="帮我建一笔"), _user(), db=None)
        assert "企业名称" in resp.answer
        assert resp.actions == []
        m_tools.assert_not_called()


# ====================================================================
# Agent 主流程
# ====================================================================


class TestAgentFlow:
    @staticmethod
    def _outcome() -> ToolOutcome:
        return ToolOutcome(
            name="list_my_applications",
            ok=True,
            data="AP20260001 | 待补件",
            refs=[BusinessRef("申请 AP20260001", "AP20260001 | 杭州示例科技 | 待补件")],
            apps=[{"id": 12, "app_no": "AP20260001"}],
            latency_ms=8,
        )

    def test_answer_flow_with_business_references(self):
        with patch(
            "app.assistant.agent._run_tool_rounds", return_value=[self._outcome()]
        ), patch("app.assistant.agent.get_client") as m_llm:
            m_llm.return_value.chat.return_value = SimpleNamespace(
                content="你有一笔待补件申请 [1]。", model="mock-model"
            )
            resp = chat(AssistantRequest(question="我有几笔待补件？"), _user(), db=None)

        assert resp.answer == "你有一笔待补件申请 [1]。"
        assert len(resp.references) == 1
        assert resp.references[0].kind == "business"
        assert resp.references[0].source == "申请 AP20260001"
        assert resp.actions[0].label == "查看申请 AP20260001"
        assert resp.actions[0].target == "/detail/12"
        assert resp.tool_calls[0].name == "list_my_applications"
        assert resp.tool_calls[0].ok is True
        assert resp.confidence == 0.8
        assert resp.model == "mock-model"

    def test_llm_failure_falls_back_to_business_data(self):
        with patch(
            "app.assistant.agent._run_tool_rounds", return_value=[self._outcome()]
        ), patch("app.assistant.agent.get_client") as m_llm:
            m_llm.return_value.chat.side_effect = RuntimeError("LLM 挂了")
            resp = chat(AssistantRequest(question="我有几笔待补件？"), _user(), db=None)

        assert "杭州示例科技" in resp.answer
        assert len(resp.references) == 1
        assert resp.references[0].kind == "business"

    def test_no_tool_result_returns_guidance(self):
        with patch("app.assistant.agent._run_tool_rounds", return_value=[]):
            resp = chat(AssistantRequest(question="我有几笔待补件？"), _user(), db=None)

        assert "暂未查询到" in resp.answer
        assert resp.confidence == 0.2

    def test_plan_falls_back_to_rule_calls(self):
        with patch("app.assistant.agent.get_client") as m_llm:
            m_llm.return_value.structured.side_effect = RuntimeError("no function calling")
            calls = _plan_calls(
                AssistantRequest(question="这笔预审为什么存疑？", app_id=12),
                None,
                set(),
                agent_type="manager",
                planner_prompt=PLANNER_SYSTEM_PROMPT,
                allowed_tools=MANAGER_TOOL_NAMES,
            )

        assert [c.tool for c in calls] == [
            "get_application_detail",
            "get_precheck_summary",
        ]

    def test_plan_uses_llm_calls_and_filters_invalid_tools(self):
        plan = ToolPlan(
            calls=[
                PlannedCall(tool="get_precheck_summary", app_id=12),
                PlannedCall(tool="none"),
            ]
        )
        with patch("app.assistant.agent.get_client") as m_llm:
            m_llm.return_value.structured.return_value = plan
            calls = _plan_calls(
                AssistantRequest(question="这笔预审为什么存疑？", app_id=12),
                None,
                set(),
                agent_type="manager",
                planner_prompt=PLANNER_SYSTEM_PROMPT,
                allowed_tools=MANAGER_TOOL_NAMES,
            )

        assert len(calls) == 1
        assert calls[0].tool == "get_precheck_summary"

    def test_rule_calls_product_choice(self):
        calls = _rule_calls(
            AssistantRequest(question="这家企业年营收 800 万，能做哪个产品？"),
            agent_type="manager",
        )
        assert [c.tool for c in calls] == ["list_products"]

    def test_rule_calls_required_materials(self):
        calls = _rule_calls(
            AssistantRequest(question="普惠小微经营贷要准备哪些材料？"),
            agent_type="manager",
        )
        assert [c.tool for c in calls] == ["get_required_materials"]
        assert calls[0].product == "普惠小微经营贷"

    def test_rule_calls_rule_explain_uses_search_policy(self):
        calls = _rule_calls(
            AssistantRequest(question="AP-H03 是什么规则？"),
            agent_type="manager",
        )
        assert [c.tool for c in calls] == ["search_policy"]
        assert calls[0].query == "AP-H03 是什么规则？"

    def test_rule_calls_todos(self):
        calls = _rule_calls(
            AssistantRequest(question="我这周有哪些要处理的？"),
            agent_type="manager",
        )
        assert [c.tool for c in calls] == ["list_my_todos"]

    def test_detect_product_prefers_long_alias(self):
        assert _detect_product("小微快贷要准备什么") == "小微快贷"
        assert _detect_product("这家企业能做抵押贷吗") == "经营性抵押贷"
        assert _detect_product("我不确定产品") is None


class TestRiskAgentIsolation:
    """风控预审助手与客户经理授信助手必须是两套不同的能力，不能只是换名。"""

    def test_risk_toolset_excludes_manager_only_tools(self):
        manager_only = {
            "list_my_applications",
            "list_my_todos",
            "preview_eligibility",
            "get_required_materials",
        }
        assert manager_only.isdisjoint(RISK_TOOL_NAMES)
        # 风控拥有复核队列与汇总工具
        assert "list_review_queue" in RISK_TOOL_NAMES
        assert "get_precheck_summary" in RISK_TOOL_NAMES
        # 经理工具集必须包含流程与材料类工具
        assert manager_only.issubset(MANAGER_TOOL_NAMES)
        assert "list_review_queue" not in MANAGER_TOOL_NAMES

    def test_risk_rule_calls_default_to_review_queue(self):
        calls = _rule_calls(AssistantRequest(question="今天有什么要做的？"), agent_type="risk")
        assert [c.tool for c in calls] == ["list_review_queue"]

    def test_risk_rule_calls_policy_question_uses_search_policy(self):
        calls = _rule_calls(
            AssistantRequest(question="AP-H03 这条规则的依据是什么？"),
            agent_type="risk",
        )
        assert calls[0].tool == "search_policy"

    def test_risk_user_can_access_other_managers_application(self):
        app = Application(id=42, app_no="AP20260099", manager_name="李四", product="普惠小微经营贷")
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = app
        risk_user = User(
            username="risk_wang",
            full_name="王五",
            role=UserRole.RISK,
            hashed_password="x",
            is_active=True,
        )
        with patch("app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo):
            result = _get_owned_app(MagicMock(), risk_user, 42)
        assert result is app
        assert result.manager_name == "李四"  # 归属不匹配也能查到

    def test_manager_user_blocked_from_other_managers_application(self):
        app = Application(id=43, app_no="AP20260100", manager_name="李四", product="普惠小微经营贷")
        fake_repo = MagicMock()
        fake_repo.get_by_id.return_value = app
        manager_user = User(
            username="mgr_zhang",
            full_name="张三",
            role=UserRole.MANAGER,
            hashed_password="x",
            is_active=True,
        )
        with patch("app.assistant.tool_impl.ApplicationRepository", return_value=fake_repo):
            result = _get_owned_app(MagicMock(), manager_user, 43)
        assert result is None
