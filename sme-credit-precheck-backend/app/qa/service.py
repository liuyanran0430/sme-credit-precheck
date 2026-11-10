"""政策问答主流程。

执行降级链（从强到弱）：
  1. 向量检索（命中足够）
  2. 向量检索 + 放宽 where（去掉 product/category 过滤）
  3. 关键词兜底（直接读 YAML 知识库）
  4. 返回"知识库暂无可靠内容"

永远不编造答案。检索不足时宁可说不知道。
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any

from app.core import config
from app.llm.factory import get_client
from app.qa.schemas import QaRequest, QaResponse, ReferenceItem, SuggestionResponse
from app.qa.intent import detect_intent
from app.qa.prompt import SYSTEM_PROMPT, build_user_prompt, truncate_answer, validate_and_clean
from app.qa.retrieval import retrieve_policy_hits as _retrieve_with_fallback
from app.rag.kb_retriever import KnowledgeHit

logger = logging.getLogger(__name__)

# 范围外回答 / 无结果回答（与 config 中默认值对齐，config 优先）
_INTENT_OUT_OF_SCOPE_FALLBACK = "我仅回答与信贷政策相关制度问题，请说明你要咨询的信贷政策、产品、材料和复核规则"
_NO_RESULT_FALLBACK = "抱歉，知识库中暂无相关内容，请联系风控运营团队补充。"

# 个人化业务问题（涉及本人名下申请）引导改用授信助手
_PERSONAL_HINT = "该问题涉及你名下的申请 / 进度 / 待办，建议改用「授信助手」查询。"
_PERSONAL_ANSWER = (
    "这是针对你名下具体申请的问题，政策问答不查询业务数据。"
    "请点击下方按钮改用「授信助手」查询申请进度、待办与补件要求；"
    "如需咨询信贷政策或材料审核标准，我可以继续回答。"
)
_PERSONAL_PRONOUNS: tuple[str, ...] = ("我的", "我有", "我这", "我名下", "我最近", "我这边")
_APPLICATION_TERMS: tuple[str, ...] = (
    "申请", "进度", "待办", "补件", "单子", "这笔", "几笔", "卡在",
)

# 推荐问题气泡（静态内容，从知识库总则与常见问题摘取）
_SUGGESTION_QUESTIONS: list[str] = [
    "普惠小微经营贷的准入要求有哪些？",
    "银行流水需要覆盖几个月？要哪些字段？",
    "AP-H03 不满足会被直接拒绝吗？",
    "营业执照登记状态需要满足什么？",
    "企业成立不满 2 年能做什么产品？",
    "征信授权书需要谁签字？",
]

# 风控角色推荐问题：偏风险判断与复核决策依据
_RISK_SUGGESTION_QUESTIONS: list[str] = [
    "当前待复核队列中有哪些高风险信号？",
    "待复核申请里有哪些规则冲突或信息不一致？",
    "命中哪些风险信号时建议直接否决？",
    "强规则命中与软规则命中在复核结论上有什么区别？",
    "企业名称不一致应该确认风险还是按误报排除？",
    "征信授权书有效期不足属于什么级别的风险？",
]


# ---------------------------------------------------------------- 主入口


def ask_question(
    req: QaRequest,
    *,
    request_id: str = "",
) -> QaResponse:
    """单轮问答主入口。

    纯业务异常内部吞掉后回退为明确提示，不向上抛异常。
    """
    start = time.perf_counter()

    if not config.QA_ENABLED:
        return _no_result_response("问答功能暂未启用", request_id=request_id)

    # 个人化业务问题：不检索、不调 LLM，引导改用授信助手
    if is_personal_business_question(req.question):
        logger.info("qa.personal_intent request_id=%s", request_id)
        return QaResponse(
            answer=_PERSONAL_ANSWER,
            references=[],
            confidence=0.0,
            used_collections=[],
            fallback_used=False,
            model=_current_model(),
            request_id=request_id,
            hint=_PERSONAL_HINT,
        )

    # 1. 意图识别
    intent = detect_intent(
        req.question,
        product_hint=req.product,
        category_hint=req.category,
    )
    if intent.kind == "out_of_scope":
        return QaResponse(
            answer=_INTENT_OUT_OF_SCOPE_MSG(),
            references=[],
            confidence=0.0,
            used_collections=[],
            fallback_used=False,
            model=_current_model(),
            request_id=request_id,
        )

    logger.info(
        "qa.ask intent=%s conf=%.2f product=%s category=%s request_id=%s",
        intent.kind, intent.confidence, intent.product_hint, intent.category_hint, request_id,
    )

    # 2. 截断 chat_history（最多 QA_MAX_HISTORY_TURNS 轮）
    history = _truncate_history(req.chat_history)

    # 3. 检索（含降级链）
    hits, used_collections, fallback_used = _retrieve_with_fallback(
        intent.kind, req.question, intent.plans
    )

    if not hits:
        return QaResponse(
            answer=_NO_RESULT_MSG(),
            references=[],
            confidence=0.0,
            used_collections=[],
            fallback_used=fallback_used,
            model=_current_model(),
            request_id=request_id,
        )

    # 4. 组装 prompt
    try:
        user_prompt, rendered_hits = build_user_prompt(
            req.question,
            hits,
            product=intent.product_hint,
            category=intent.category_hint,
            chat_history=history,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("qa.build_prompt 失败：%s", exc)
        return _no_result_response(request_id=request_id)

    # 5. LLM 生成
    actual_model: str = ""
    try:
        llm = get_client()
        llm_resp = llm.chat(
            system=SYSTEM_PROMPT,
            user=user_prompt,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=800,
        )
        raw_answer = llm_resp.content or ""
        actual_model = llm_resp.model or ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("qa.llm 调用失败：%s", exc)
        # LLM 挂了就把 top3 命中直接列出来，且跳过后处理（因为没有引用编号）
        raw_answer = _fallback_hits_as_text(hits[:3])
        actual_model = config.LLM_MODEL or ""
        cleaned_answer = raw_answer
        references_raw: list[dict[str, Any]] = []
    else:
        # 6. 后处理：引用校验 + 脱敏 + 截断
        cleaned_answer, references_raw = validate_and_clean(raw_answer, rendered_hits)

    final_answer = truncate_answer(cleaned_answer, config.QA_MAX_ANSWER_CHARS)

    # 7. 置信度：意图置信度 × 平均命中分数（没有引用则大幅降权）
    hit_score_avg = (
        sum(h.score for h in hits[: len(references_raw)]) / max(1, len(references_raw))
        if references_raw
        else 0.4 * intent.confidence
    )
    confidence = round(min(0.98, 0.6 * intent.confidence + 0.4 * hit_score_avg), 3)

    duration_ms = int((time.perf_counter() - start) * 1000)
    logger.info(
        "qa.ask 完成 conf=%.3f refs=%d fallback=%s duration_ms=%d request_id=%s",
        confidence, len(references_raw), fallback_used, duration_ms, request_id,
    )

    return QaResponse(
        answer=final_answer,
        references=[ReferenceItem(**ref) for ref in references_raw],
        confidence=confidence,
        used_collections=sorted(set(used_collections)),
        fallback_used=fallback_used,
        model=actual_model or _current_model(),
        request_id=request_id,
    )


def get_suggestions(role: str | None = None) -> SuggestionResponse:
    """返回推荐问题气泡（静态）。风控角色返回风险判断导向的问题。"""
    pool = _RISK_SUGGESTION_QUESTIONS if role == "risk" else _SUGGESTION_QUESTIONS
    return SuggestionResponse(questions=list(pool[:6]))


# ---------------------------------------------------------------- 内部工具


def is_personal_business_question(question: str) -> bool:
    """个人代词 + 申请语义同时命中，判定为应改用授信助手的业务问题。"""
    text = question.strip()
    if not any(pronoun in text for pronoun in _PERSONAL_PRONOUNS):
        return False
    return any(term in text for term in _APPLICATION_TERMS)


# 兼容既有内部调用与测试命名
_is_personal_business_question = is_personal_business_question


def _truncate_history(chat_history: list[Any] | None) -> list[dict[str, str]] | None:
    if not chat_history:
        return None
    turns = max(0, config.QA_MAX_HISTORY_TURNS)
    # 一轮 = 1 user + 1 assistant；取最近 turns 轮
    flat: list[dict[str, str]] = []
    for msg in chat_history:
        role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
        if not role or not content:
            continue
        flat.append({"role": role, "content": str(content)})

    # 保留最近的 turns 轮（每轮 2 条，若最后不成对则保留完整 user 部分）
    recent = flat[-2 * turns :] if turns > 0 else []
    return recent or None


def _fallback_hits_as_text(hits: list[KnowledgeHit]) -> str:
    ll: list[str] = ["以下是知识库中可能相关的内容，供参考：", ""]
    for i, h in enumerate(hits, 1):
        meta = h.metadata or {}
        source = meta.get("source", "")
        text = re.sub(r"\s+", " ", h.text).strip()[:150]
        ll.append(f"[{i}] {source}  {text}")
    return "\n".join(ll)


def _INTENT_OUT_OF_SCOPE_MSG() -> str:
    return config.QA_OUT_OF_SCOPE_MSG or _INTENT_OUT_OF_SCOPE_FALLBACK


def _NO_RESULT_MSG() -> str:
    return config.QA_NO_RESULT_MSG or _NO_RESULT_FALLBACK


def _no_result_response(message: str, *, request_id: str) -> QaResponse:
    return QaResponse(
        answer=message,
        references=[],
        confidence=0.0,
        used_collections=[],
        fallback_used=False,
        model=_current_model(),
        request_id=request_id,
    )


def _current_model() -> str:
    try:
        return config.LLM_MODEL or ""
    except Exception:
        return ""
