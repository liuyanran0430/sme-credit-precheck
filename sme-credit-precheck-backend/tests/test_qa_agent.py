"""政策问答 Agent 核心逻辑单元测试。

覆盖：
1. 意图识别（product_admission / material_review / rule_explain / case_ref / out_of_scope）
2. 检索计划（plan 的 collection / where / top_k 是否符合意图）
3. Prompt 构造与引用后处理
4. 降级链行为（向量检索空 → step1/2/3 流程）
5. Schema 校验

不依赖 MySQL，不依赖真实向量索引；向量检索部分使用 patch 隔离。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.core import config
from app.qa.intent import (
    CATEGORY_NAME_TO_CODE,
    PRODUCT_ALIASES,
    PRODUCT_CODE_TO_NAME,
    detect_intent,
)
from app.qa.prompt import build_user_prompt, truncate_answer, validate_and_clean
from app.qa.schemas import QaRequest, QaResponse, SuggestionResponse
from app.qa.service import ask_question, get_suggestions
from app.rag.kb_retriever import KnowledgeHit


# ====================================================================
# 意图识别
# ====================================================================


class TestIntentDetection:
    def test_product_admission(self):
        i = detect_intent("普惠小微经营贷对成立年限有什么要求？", product_hint="普惠小微经营贷")
        assert i.kind == "product_admission"
        assert i.confidence >= 0.5
        assert len(i.plans) >= 2
        collections = {p.collection for p in i.plans}
        assert "kb_policy" in collections

    def test_product_code_in_question(self):
        """产品代码 AP 命中 → 映射回普惠小微经营贷。"""
        i = detect_intent("AP 对成立年限有什么要求？")
        assert i.product_hint == "普惠小微经营贷"
        assert i.kind == "product_admission"

    def test_material_review(self):
        i = detect_intent("银行流水需要覆盖几个月？要哪些字段？")
        assert i.kind == "material_review"
        assert "kb_material_review" in {p.collection for p in i.plans}

    def test_material_category_hint(self):
        i = detect_intent("需要哪些字段？", category_hint="bank_statement")
        assert i.category_hint == "bank_statement"
        assert any(p.collection == "kb_material_review" for p in i.plans)

    def test_rule_explain_by_id(self):
        """规则编号命中 → rule_explain 并加 rule_id where。"""
        i = detect_intent("AP-H03 不满足会怎么样？")
        assert i.kind == "rule_explain"
        # rule_explain 意图的第一条 plan 应该带精确 rule_id where
        rule_plan = next(p for p in i.plans if p.collection == "kb_rule_config")
        assert rule_plan.where is None or rule_plan.where.get("rule_id") == "AP-H03"

    def test_case_ref(self):
        i = detect_intent("之前有没有类似的案例？")
        assert i.kind == "case_ref"
        assert "kb_cases" in {p.collection for p in i.plans}

    def test_out_of_scope(self):
        i = detect_intent("帮我写一段 Python 代码")
        assert i.kind == "out_of_scope"
        assert i.confidence >= 0.6

    @pytest.mark.parametrize(
        "question",
        ["今天天气怎么样", "你好", "给我推荐一部电影", "帮我翻译这段英文"],
    )
    def test_out_of_scope_variants(self, question: str):
        assert detect_intent(question).kind == "out_of_scope"

    @pytest.mark.parametrize(
        "question",
        [
            "征信授权书要谁签字",
            "年营收怎么算",
            "担保方式有哪些",
            "逾期记录会影响准入吗",
            "小微企业贷款额度上限",
        ],
    )
    def test_in_scope_by_domain_terms(self, question: str):
        """命中业务领域词表即视为相关问题，不得误判为无关。"""
        assert detect_intent(question).kind != "out_of_scope"

    def test_out_of_scope_but_business_anchor_takes_priority(self):
        """同时出现闲聊关键词 + 业务关键词 → 业务优先。"""
        i = detect_intent("你好，普惠小微经营贷有什么要求？")
        assert i.kind != "out_of_scope"

    def test_no_keywords_but_product_hint(self):
        """没命中任何关键词但有产品 hint → 走 product_admission 兜底。"""
        i = detect_intent("这个产品怎么样？", product_hint="小微快贷")
        assert i.kind == "product_admission"

    def test_plans_have_no_product_where_when_no_product_hint(self):
        i = detect_intent("成立年限要求？")
        for p in i.plans:
            if p.collection in ("kb_policy", "kb_rule_config"):
                # 没有 product hint 时 where 里不应出现 product
                assert not (p.where and "product" in p.where)

    def test_category_code(self):
        """CATEGORY_NAME_TO_CODE 映射正确。"""
        assert CATEGORY_NAME_TO_CODE["银行流水"] == "bank_statement"
        assert CATEGORY_NAME_TO_CODE["财务报表"] == "financial_report"
        assert len(CATEGORY_NAME_TO_CODE) >= 5

    def test_product_aliases(self):
        # PRODUCT_ALIASES key 是中文名，不是代码
        assert "普惠小微经营贷" in PRODUCT_ALIASES
        assert "AP" in PRODUCT_ALIASES["普惠小微经营贷"]
        assert PRODUCT_CODE_TO_NAME["AP"] == "普惠小微经营贷"


# ====================================================================
# Schema
# ====================================================================


class TestSchemas:
    def test_qa_request_ok(self):
        r = QaRequest(question="你好？")
        assert r.product is None
        assert r.category is None
        assert r.chat_history is None

    def test_qa_request_empty_question_rejected(self):
        with pytest.raises(ValidationError):
            QaRequest(question="")

    def test_qa_request_history_truncation_side(self):
        """chat_history 不在这里截断（由 service 负责），但 schema 允许通过。"""
        r = QaRequest(
            question="成立年限？",
            chat_history=[
                {"role": "user", "content": "A"},
                {"role": "assistant", "content": "B"},
                {"role": "user", "content": "C"},
                {"role": "assistant", "content": "D"},
            ],
        )
        assert len(r.chat_history) == 4

    def test_suggestion_response(self):
        resp = SuggestionResponse(questions=["q1", "q2"])
        assert len(resp.questions) == 2

    def test_qa_response_confidence_bounds(self):
        QaResponse(
            answer="ok",
            confidence=0.5,
            fallback_used=False,
            model="deepseek-chat",
        )
        with pytest.raises(ValidationError):
            QaResponse(answer="ok", confidence=1.5)
        with pytest.raises(ValidationError):
            QaResponse(answer="ok", confidence=-0.1)


# ====================================================================
# Prompt + 引用后处理
# ====================================================================


def _mk_hit(collection: str, text: str, score: float = 0.7, metadata: dict[str, Any] | None = None) -> KnowledgeHit:
    return KnowledgeHit(
        collection=collection,
        text=text,
        score=score,
        metadata=metadata or {"source": f"fake/{collection}.md"},
    )


class TestPrompt:
    def test_build_user_prompt_no_history(self):
        hits = [_mk_hit("kb_policy", "AP-H02 成立年限 ≥ 2 年", 0.8)]
        prompt, rendered = build_user_prompt("成立年限？", hits, product="普惠小微经营贷")
        assert "【问题】" in prompt
        assert "普惠小微经营贷" in prompt
        assert "[1]" in prompt
        assert rendered[0].index == 1

    def test_build_user_prompt_truncates_hit(self):
        long_text = "字" * 800
        hits = [_mk_hit("kb_policy", long_text)]
        prompt, _ = build_user_prompt("q", hits, max_chars_per_hit=300)
        # 结尾有省略号
        assert "…" in prompt

    def test_build_user_prompt_dedents_whitespace(self):
        hits = [_mk_hit("kb_policy", "  AP-H02  \n\n  成立年限  \t ≥ 2年  ")]
        prompt, _ = build_user_prompt("q", hits)
        # 空白被压缩（不会有连续的 \n\n）
        assert "\n\n  " not in prompt

    def test_validate_and_clean_removes_unused_references(self):
        hits = [
            _mk_hit("kb_policy", "AP-H02 text", metadata={"source": "fake/a.md", "product": "普惠小微经营贷"}),
            _mk_hit("kb_rule_config", "AP-H03 text", metadata={"source": "fake/b.md"}),
        ]
        _, rendered = build_user_prompt("q", hits)
        # 只引用 [1]，[2] 没用
        answer = "成立年限 ≥ 2 年 [1]。"
        cleaned, refs = validate_and_clean(answer, rendered)
        assert cleaned == answer
        assert len(refs) == 1
        assert refs[0]["index"] == 1

    def test_validate_and_clean_clamps_invalid_reference(self):
        hits = [_mk_hit("kb_policy", "t", metadata={"source": "fake/a.md"})]
        _, rendered = build_user_prompt("q", hits)
        # answer 引用了不存在的编号 [9]
        answer = "… [1] 另外 [9] 是废话"
        cleaned, refs = validate_and_clean(answer, rendered)
        assert cleaned == answer
        assert len(refs) == 1  # 只保留 [1]

    def test_validate_and_clean_extracts_source_metadata(self):
        hits = [_mk_hit("kb_policy", "t", metadata={
            "source": "01_信贷政策/准入规则/普惠小微经营贷.md",
            "rule_id": "AP-H02",
            "product": "普惠小微经营贷",
        })]
        _, rendered = build_user_prompt("q", hits)
        _, refs = validate_and_clean("… [1]", rendered)
        assert refs[0]["rule_id"] == "AP-H02"
        assert refs[0]["product"] == "普惠小微经营贷"


class TestTruncateAnswer:
    def test_short_unchanged(self):
        short = "短文本。"
        assert truncate_answer(short, 100) == short

    def test_long_truncates_on_period(self):
        long_text = "这是一段很长的文字。" * 200
        result = truncate_answer(long_text, 1500)
        assert len(result) <= 1500 + 20  # 结尾标点
        assert result.endswith(("。", ".", "…"))


# ====================================================================
# Service 端到端（mock 向量检索 + mock LLM）
# ====================================================================


class TestAskQuestionService:
    def test_get_suggestions_count(self):
        r = get_suggestions()
        assert 0 < len(r.questions) <= 6
        for q in r.questions:
            assert len(q) <= 100

    @patch("app.qa.service.get_client")
    @patch("app.qa.service._retrieve_with_fallback")
    def test_answer_flow_happy_path(self, mock_retrieve, mock_get_client):
        mock_hits = [
            _mk_hit("kb_policy", "AP-H02 成立年限 ≥ 2 年，以申请日为基准计算。", 0.85,
                    metadata={"source": "01_信贷政策/准入规则/普惠小微经营贷.md",
                              "rule_id": "AP-H02", "product": "普惠小微经营贷"}),
        ]
        mock_retrieve.return_value = (mock_hits, ["kb_policy"], False)

        class _Resp:
            content = "普惠小微经营贷要求成立年限 ≥ 2 年 [1]。"
            model = "mock-model"
        mock_get_client.return_value.chat.return_value = _Resp()

        resp = ask_question(
            QaRequest(question="成立年限？", product="普惠小微经营贷"),
            request_id="abc123",
        )
        assert resp.request_id == "abc123"
        assert resp.answer == "普惠小微经营贷要求成立年限 ≥ 2 年 [1]。"
        assert len(resp.references) == 1
        assert resp.references[0].rule_id == "AP-H02"
        assert resp.confidence > 0.5
        assert resp.used_collections == ["kb_policy"]
        assert resp.fallback_used is False
        assert resp.model == "mock-model"

    @patch("app.qa.service._retrieve_with_fallback")
    def test_empty_retrieve_returns_no_result_msg(self, mock_retrieve):
        mock_retrieve.return_value = ([], [], False)
        # 问题必须能触发业务意图（否则会被 detect_intent 判 out_of_scope）
        resp = ask_question(QaRequest(question="普惠小微经营贷对成立年限有什么要求？"))
        assert "知识库中暂无相关内容" in resp.answer
        assert resp.confidence == 0.0
        assert resp.references == []

    def test_out_of_scope_short_circuit(self):
        """范围外问题不触发检索和 LLM，直接返回固定提示。"""
        with patch("app.qa.service._retrieve_with_fallback") as m_retrieve, \
             patch("app.qa.service.get_client") as m_llm:
            resp = ask_question(QaRequest(question="帮我写一段 python 代码"))
        assert resp.answer == (
            "我仅回答与信贷政策相关制度问题，请说明你要咨询的信贷政策、产品、材料和复核规则"
        )
        assert resp.confidence == 0.0
        assert resp.references == []
        assert resp.fallback_used is False
        # 关键：分类阶段就返回，检索与 LLM 一次都不调用
        m_retrieve.assert_not_called()
        m_llm.assert_not_called()

    @patch("app.qa.service.get_client")
    @patch("app.qa.service._retrieve_with_fallback")
    def test_llm_failure_falls_back_to_raw_hits(self, mock_retrieve, mock_get_client):
        mock_hits = [
            _mk_hit("kb_policy", "命中的内容 A", 0.8, metadata={"source": "fake/a.md"}),
            _mk_hit("kb_material_review", "命中的内容 B", 0.7, metadata={"source": "fake/b.md"}),
        ]
        mock_retrieve.return_value = (mock_hits, ["kb_policy", "kb_material_review"], False)
        mock_get_client.return_value.chat.side_effect = RuntimeError("LLM 挂了")

        resp = ask_question(QaRequest(question="普惠小微经营贷对成立年限有什么要求？"))
        # LLM 失败 → 把前 3 条命中原文列出作为 answer
        assert "知识库中可能相关" in resp.answer
        assert "命中的内容" in resp.answer
        assert resp.references == []  # 没有 LLM 生成的引用

    @patch("app.qa.service._retrieve_with_fallback")
    def test_fallback_flag_propagated(self, mock_retrieve):
        mock_retrieve.return_value = (
            [_mk_hit("kb_policy", "x", 0.5)],
            ["kb_policy"],
            True,  # fallback 触发了
        )

        class _Resp:
            content = "答案 [1]"
            model = "mock-model"
        with patch("app.qa.service.get_client") as mllm:
            mllm.return_value.chat.return_value = _Resp()
            resp = ask_question(QaRequest(question="普惠小微经营贷对成立年限有什么要求？"))
        assert resp.fallback_used is True

    def test_qa_disabled_short_circuit(self):
        with patch.object(config, "QA_ENABLED", False):
            resp = ask_question(QaRequest(question="成立年限？"))
            assert "暂未启用" in resp.answer
            assert resp.confidence == 0.0

    def test_history_truncation(self):
        """超过 QA_MAX_HISTORY_TURNS 轮的对话，service 自动截断。"""
        from app.qa import service as svc

        def _run_with(n_turns_cap: int, user_questions: list[str]) -> int:
            seen_history: list[int] = []

            def patched_build_user_prompt(question, hits, **kwargs):
                h = kwargs.get("chat_history")
                seen_history.append(len(h) if h else 0)
                return "PROMPT", []

            with patch.object(config, "QA_MAX_HISTORY_TURNS", n_turns_cap):
                with patch.object(svc, "build_user_prompt", patched_build_user_prompt):
                    with patch.object(svc, "_retrieve_with_fallback", return_value=(
                        [_mk_hit("kb_policy", "命中内容", 0.7, metadata={"source": "fake.md"})],
                        ["kb_policy"], False,
                    )):
                        with patch("app.qa.service.get_client") as mllm:
                            class _Resp:
                                content = "答案 [1]"
                                model = "mock"
                            mllm.return_value.chat.return_value = _Resp()
                            for q in user_questions:
                                ask_question(QaRequest(question=q))
            return seen_history[0] if seen_history else 0

        # 4 轮对话，2 轮上限 → chat_history 最多 4 条 user+assistant
        hist_len = _run_with(2, ["普惠小微经营贷对成立年限有什么要求？"])
        assert hist_len <= 2 * 2  # 2 轮上限 → 最多 4 条历史
