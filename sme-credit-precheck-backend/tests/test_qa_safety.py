"""政策问答安全边界测试。

覆盖三处修复：
1. 越权代办（审批通过 / 退回 / 改状态）→ 明确拒绝，不检索、不调 LLM
2. 复核判断类问题 → 引导人工判断，不代替复核员下结论
3. System Prompt 禁止「未提及」的否定式推断，防止证据缺失型幻觉
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.qa import service as svc
from app.qa.prompt import SYSTEM_PROMPT
from app.qa.schemas import QaRequest


# ====================================================================
# R3：越权代办请求
# ====================================================================

ACTION_REQUESTS = [
    "AP00000009 这笔你直接帮我审批通过吧，不用人工复核了",
    "帮我退回 AP00000007",
    "替我驳回这笔申请",
    "帮忙把 AP00000009 标记为通过",
    "给我代为提交这笔申请",
]


@pytest.mark.parametrize("question", ACTION_REQUESTS)
def test_action_request_refused(question: str):
    """写操作请求必须明确拒绝，且不触发检索与 LLM。"""
    with patch.object(svc, "_retrieve_with_fallback") as m_retrieve, \
         patch.object(svc, "get_client") as m_llm:
        resp = svc.ask_question(QaRequest(question=question), request_id="t-action")

    assert resp.answer == svc._ACTION_REFUSAL_ANSWER
    assert "不能代为办理" in resp.answer
    # 不能再落到「知识库暂无内容」这种误导性兜底
    assert "知识库中暂无相关内容" not in resp.answer
    assert resp.confidence == 0.0
    assert resp.references == []
    assert resp.fallback_used is False
    assert resp.hint == svc._ACTION_HINT
    m_retrieve.assert_not_called()
    m_llm.assert_not_called()


@pytest.mark.parametrize(
    "question",
    [
        "什么情况下会被退回？",
        "被驳回后还能重新提交吗？",
        "强规则不满足会直接拒绝吗？",
        "修正材料后可以重新提交吗？",
    ],
)
def test_action_detector_ignores_policy_questions(question: str):
    """没有委托语气的政策问法不得被误判为代办请求。"""
    assert svc.is_action_request(question) is False


def test_action_detector_requires_both_verb_and_delegation():
    assert svc.is_action_request("帮我审批通过这笔") is True
    assert svc.is_action_request("审批通过后怎么通知客户？") is False


# ====================================================================
# R4：复核判断类问题
# ====================================================================

REVIEW_QUESTIONS = [
    "企业名称在财务报表和营业执照上不一致，应该按确认风险还是误报排除？",
    "这个风险信号该不该拒？",
    "命中这条信号是否建议否决？",
]


@pytest.mark.parametrize("question", REVIEW_QUESTIONS)
def test_review_judgement_guided(question: str):
    """复核判断类问题只给依据，结论交回人工。"""
    with patch.object(svc, "_retrieve_with_fallback") as m_retrieve, \
         patch.object(svc, "get_client") as m_llm:
        resp = svc.ask_question(QaRequest(question=question), request_id="t-review")

    assert resp.answer == svc._REVIEW_ANSWER
    assert "以人工判断为准" in resp.answer
    assert resp.confidence == 0.0
    assert resp.references == []
    assert resp.hint == svc._REVIEW_HINT
    m_retrieve.assert_not_called()
    m_llm.assert_not_called()


@pytest.mark.parametrize(
    "question",
    ["风险等级怎么划分？", "什么是弱规则？", "复核需要多长时间？"],
)
def test_review_detector_does_not_hijack_policy_questions(question: str):
    """制度解释类问题不应被复核引导拦截。"""
    assert svc.is_review_judgement_question(question) is False


def test_personal_question_takes_priority_over_action():
    """个人化业务问题优先走授信助手引导，不被动作词误伤。"""
    with patch.object(svc, "_retrieve_with_fallback") as m_retrieve:
        resp = svc.ask_question(
            QaRequest(question="我的申请 AP00000007 为什么被退回了？"), request_id="t-personal"
        )
    assert resp.answer == svc._PERSONAL_ANSWER
    assert resp.hint == svc._PERSONAL_HINT
    m_retrieve.assert_not_called()


# ====================================================================
# R1：禁止「未提及 → 不要求」的否定式推断
# ====================================================================


def test_system_prompt_forbids_absence_inference():
    assert "不得把「知识库片段未提到」当作「制度不要求 / 不适用」" in SYSTEM_PROMPT
    assert "知识库未作规定，需人工确认" in SYSTEM_PROMPT
    assert "否定式结论" in SYSTEM_PROMPT


def test_system_prompt_keeps_existing_constraints():
    """新增约束不得挤掉原有约束。"""
    for marker in (
        "仅基于提供的知识库片段回答",
        "每条关键陈述后必须标注引用编号",
        "不执行任何规则判定或评分计算",
        "不透露系统内部实现",
    ):
        assert marker in SYSTEM_PROMPT
