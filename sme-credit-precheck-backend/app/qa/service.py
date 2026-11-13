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
from app.services.rule_config import load_rule_config

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

    # 代办写操作请求：明确拒绝，不检索、不调 LLM
    if is_action_request(req.question):
        logger.info("qa.action_refusal request_id=%s", request_id)
        return QaResponse(
            answer=_ACTION_REFUSAL_ANSWER,
            references=[],
            confidence=0.0,
            used_collections=[],
            fallback_used=False,
            model=_current_model(),
            request_id=request_id,
            hint=_ACTION_HINT,
        )

    # 复核判断类问题：只给依据，引导人工判断
    if is_review_judgement_question(req.question):
        logger.info("qa.review_judgement request_id=%s", request_id)
        return QaResponse(
            answer=_REVIEW_ANSWER,
            references=[],
            confidence=0.0,
            used_collections=[],
            fallback_used=False,
            model=_current_model(),
            request_id=request_id,
            hint=_REVIEW_HINT,
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

    # 3.1 产品准入 / 规则解释：直接加载该产品的规则 YAML，作为高优先级证据注入
    #      （向量库可能未收录规则配置，且具体准入门槛只在 YAML 里）
    if intent.product_hint and intent.kind in ("product_admission", "rule_explain", "general"):
        rule_hit = _build_rule_config_hit(intent.product_hint)
        if rule_hit is not None:
            hits = [rule_hit] + hits
            if "kb_rule_config" not in used_collections:
                used_collections.append("kb_rule_config")

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


def _build_rule_config_hit(product: str) -> KnowledgeHit | None:
    """把产品准入规则 YAML 渲染成人类可读的文本，作为高优先级证据。

    具体准入门槛（强/弱规则、阈值、评分等级）只存在于 YAML，
    向量库不一定收录，因此产品准入类问题直接读文件更可靠。
    """
    config = load_rule_config(product)
    if not config:
        return None

    product_name = str(config.get("product") or product)
    version = str(config.get("version") or "")
    rules = config.get("rules") or []

    hard_rules = [r for r in rules if r.get("kind") == "hard"]
    soft_rules = [r for r in rules if r.get("kind") == "soft"]

    lines: list[str] = [f"【{product_name} 准入规则（版本 {version}）】", ""]

    lines.append("一、强规则（任一不满足 → 直接拒绝）：")
    for r in hard_rules:
        rid = r.get("rule_id", "")
        name = r.get("rule_name", "")
        detail = r.get("detail_zh", "")
        lines.append(f"  - {rid} {name}：{detail}")
    if not hard_rules:
        lines.append("  （无）")

    lines.append("")
    lines.append("二、弱规则（不满足不拦截，影响打分/评级）：")
    for r in soft_rules:
        rid = r.get("rule_id", "")
        name = r.get("rule_name", "")
        detail = r.get("detail_zh", "")
        lines.append(f"  - {rid} {name}：{detail}")
    if not soft_rules:
        lines.append("  （无）")

    scoring = config.get("scoring") or {}
    thresholds = scoring.get("level_thresholds") or {}
    labels = scoring.get("level_label") or {}
    notes = scoring.get("level_note") or {}
    if thresholds:
        lines.append("")
        lines.append("三、评分等级：")
        for level in ("A", "B", "C", "D"):
            if level not in thresholds:
                continue
            rng = thresholds[level]
            label = labels.get(level, "")
            note = notes.get(level, "")
            lines.append(f"  - {level}（{label}）：得分 {rng[0]}-{rng[1]}，{note}")

    conclusion = config.get("conclusion_logic") or {}
    if conclusion:
        lines.append("")
        lines.append("四、结论口径：")
        logic_map = {
            "hard_rule_fail": "强规则不通过",
            "completeness_issue": "材料完整性问题",
            "consistency_high_fail": "一致性高风险项不通过",
            "soft_rule_fail_count_ge_3": "弱规则不通过 ≥ 3 条",
            "else": "其余情况",
        }
        action_map = {
            "reject": "拒绝",
            "manual": "待补件",
            "attention": "待人工核验",
            "pass": "通过（按得分评级）",
        }
        for key, action in conclusion.items():
            desc = logic_map.get(key, key)
            act = action_map.get(str(action), str(action))
            lines.append(f"  - {desc} → {act}")

    text = "\n".join(lines)
    source = f"03_规则配置/准入规则/rule_{product}.yaml"
    return KnowledgeHit(
        collection="kb_rule_config",
        text=text,
        score=1.0,
        metadata={
            "source": source,
            "product": product_name,
            "version": version,
            "kind": "rule_config",
        },
    )


def is_personal_business_question(question: str) -> bool:
    """个人代词 + 申请语义同时命中，判定为应改用授信助手的业务问题。"""
    text = question.strip()
    if not any(pronoun in text for pronoun in _PERSONAL_PRONOUNS):
        return False
    return any(term in text for term in _APPLICATION_TERMS)


# 兼容既有内部调用与测试命名
_is_personal_business_question = is_personal_business_question


# 要求代替办理写操作（审批/退回/改状态）：QA 无写能力，必须明确拒绝而非答"暂无内容"
_ACTION_REFUSAL_ANSWER = (
    "我不能代为办理审批、退回或修改申请状态等业务动作。"
    "政策问答只解释制度与规则，不读写任何业务数据；"
    "如需处理这笔申请，请到申请详情页或复核队列由人工操作。"
)
_ACTION_HINT = "涉及业务动作办理，请到对应申请页面人工处理。"

# 复核判断类问题：只给依据，不代替人工下结论
_REVIEW_ANSWER = (
    "这属于需要人工判断的复核问题。我只能提供规则依据与风险信号，"
    "不代替风控人员下结论——请结合证据、识别置信度与材料情况判断，"
    "最终复核结论以人工判断为准。"
)
_REVIEW_HINT = "复核结论需人工判断，建议先查看该申请的预审报告与风险信号。"

# 动作词与委托语气同时命中才判为越权办理请求，避免误伤「什么情况会被退回」这类政策问法
_ACTION_VERBS: tuple[str, ...] = (
    "审批通过", "直接通过", "帮我通过", "代为审批", "批准",
    "代为提交", "帮我提交", "代为拒绝", "直接拒绝",
    "退回", "驳回", "修改状态", "改状态", "标记为",
)
_DELEGATION_MARKERS: tuple[str, ...] = ("帮我", "替我", "代为", "给我", "你帮我", "帮忙")

# 复核判断语气：仅在明确要求给出「确认/排除/否决」结论时触发
_REVIEW_JUDGEMENT_TERMS: tuple[str, ...] = (
    "确认风险", "误报排除", "按误报", "确认还是排除", "该不该拒",
    "建议否决", "是否否决", "判定为风险",
)


def is_action_request(question: str) -> bool:
    """是否为要求代办的写操作请求（审批通过 / 退回 / 改状态等）。"""
    text = question.strip()
    if not any(marker in text for marker in _DELEGATION_MARKERS):
        return False
    return any(verb in text for verb in _ACTION_VERBS)


def is_review_judgement_question(question: str) -> bool:
    """是否为需要人工下结论的复核判断问题。"""
    text = question.strip()
    return any(term in text for term in _REVIEW_JUDGEMENT_TERMS)


# 兼容内部命名风格
_is_action_request = is_action_request
_is_review_judgement_question = is_review_judgement_question



def _truncate_history(chat_history: list[Any] | None) -> list[dict[str, str]] | None:
    if not chat_history:
        return None
    turns = max(0, config.QA_MAX_HISTORY_TURNS)
    # 单轮 = 1 user + 1 assistant；取最近 turns 轮
    flat: list[dict[str, str]] = []
    for msg in chat_history:
        role = getattr(msg, "role", None) or (msg.get("role") if isinstance(msg, dict) else None)
        content = getattr(msg, "content", None) or (msg.get("content") if isinstance(msg, dict) else None)
        if not role or not content:
            continue
        # 单条内容过长会撑爆 prompt，截到 1200 字（回答上限 1500，留有余量）
        text = str(content)
        if len(text) > 1200:
            text = text[:1200].rstrip() + "…"
        flat.append({"role": role, "content": text})

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
