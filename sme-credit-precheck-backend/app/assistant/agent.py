"""授信助手 Agent 主流程（P2：只读问答 + 8 个工具 + 预填动作）。

流程：
  1. 领域分类（纯规则，无关问题零 LLM、零工具）
  2. 新建申请意图（只预填，不提交，不产生任何写操作）
  3. LLM 规划工具（失败降级为规则直连）
  4. 执行工具（只读 + 归属校验 + 单工具超时）
  5. 最多 N 轮，去重后继续规划
  6. 基于业务数据 + 知识库依据生成答案，统一引用编号后处理
  7. 纯政策问题追加「查看完整政策问答」跳转
"""

from __future__ import annotations

import logging
import re
import time
from typing import Any, Literal, Sequence

from sqlalchemy.orm import Session

from app.assistant.prompt import (
    PLANNER_SYSTEM_PROMPT,
    RISK_PLANNER_PROMPT,
    RISK_SYSTEM_PROMPT,
    SYSTEM_PROMPT,
    build_answer_prompt,
    build_planning_prompt,
    fallback_answer,
    outcomes_to_hits,
    truncate_history,
)
from app.assistant.schemas import (
    AssistantAction,
    AssistantRequest,
    AssistantResponse,
    ToolCallTrace,
)
from app.assistant.tool_impl import BusinessRef, ToolOutcome, execute_tool
from app.assistant.tools import (
    MANAGER_TOOL_NAMES,
    RISK_TOOL_NAMES,
    TOOL_NAMES,
    PlannedCall,
    ToolPlan,
)
from app.core import config
from app.llm.factory import get_client
from app.models.user import User
from app.qa.intent import PRODUCT_ALIASES, RULE_ID_RE, _DOMAIN_TERMS
from app.qa.prompt import RenderedHit, truncate_answer, validate_and_clean
from app.qa.schemas import ReferenceItem
from app.services.rule_config import list_rule_configs

logger = logging.getLogger(__name__)

_OUT_OF_SCOPE_MSG = "我只回答与授信业务办理相关的问题，请说明你要查询的申请、进度或材料要求。"
_RISK_OUT_OF_SCOPE_MSG = "我只回答与风控复核相关的问题，请说明你要复核的申请、风险信号或复核关注点。"
_DISABLED_MSG = "授信助手暂未启用，请稍后再试。"
_NO_DATA_MSG = "暂未查询到相关业务数据，请确认申请编号或换个问法再试。"

AgentType = Literal["manager", "risk"]


def _agent_prompts(agent_type: AgentType) -> tuple[str, str, frozenset[str]]:
    """按角色返回（作答 system prompt、规划 system prompt、工具白名单）。"""
    if agent_type == "risk":
        return RISK_SYSTEM_PROMPT, RISK_PLANNER_PROMPT, RISK_TOOL_NAMES
    return SYSTEM_PROMPT, PLANNER_SYSTEM_PROMPT, MANAGER_TOOL_NAMES

# 助手专属业务词（与政策问答词表做并集，两个分类器互不修改）
_ASSISTANT_TERMS: tuple[str, ...] = (
    "我的", "我有", "我这", "我名下", "几笔", "进度", "待办", "这笔",
    "这个申请", "该申请", "申请号", "申请编号", "卡在", "缺什么", "缺哪些",
    "补件", "退回", "人工核验", "风控复核", "通过率", "存疑", "风险信号",
    "状态", "预审报告",
)

# 纯政策问题特征词（用于无业务数据时追加「查看完整政策问答」）
_POLICY_TERMS: tuple[str, ...] = (
    "政策", "制度", "规则", "准入", "标准", "要求", "解释", "含义",
    "材料", "流水", "财报", "报表", "征信", "纳税", "营业执照", "成立年限",
)

_APP_NO_RE = re.compile(r"\b(?:AP|AK|AJ|AE)\d{8}\b")

# P2：新建申请意图（只预填弹窗，绝不调用创建接口）
_PREFILL_TERMS: tuple[str, ...] = (
    "新建申请", "新建一笔", "建一笔", "创建申请", "发起申请",
    "发起一笔", "开一笔", "帮我建", "申请一笔",
)
_AMOUNT_CONTEXT_RE = re.compile(
    r"(?:申请金额|申请额度|贷款金额|贷款额度|额度|申请|借|贷)\s*([\d.]+)\s*万"
)
_AMOUNT_WAN_RE = re.compile(r"([\d.]+)\s*万")
_COMPANY_RE = re.compile(
    r"([\u4e00-\u9fa5A-Za-z0-9（）()]{2,40}?(?:有限责任公司|有限公司|公司))"
)

# 助手会话保留最近 5 轮历史（与政策问答独立）
_MAX_HISTORY_TURNS = 5


def chat(
    req: AssistantRequest,
    user: User,
    db: Session,
    *,
    agent_type: AgentType = "manager",
    request_id: str = "",
) -> AssistantResponse:
    """单轮对话入口，任何异常都降级为可读回答，不向上抛。"""
    start = time.perf_counter()
    answer_prompt_text, planner_prompt_text, allowed_tools = _agent_prompts(agent_type)
    out_of_scope_msg = (
        _RISK_OUT_OF_SCOPE_MSG if agent_type == "risk" else _OUT_OF_SCOPE_MSG
    )

    try:
        if not config.ASSISTANT_ENABLED:
            return _response(
                _DISABLED_MSG,
                confidence=0.0,
                request_id=request_id,
            )

        if not _in_scope(req.question, req.app_id):
            return _response(
                out_of_scope_msg,
                confidence=0.0,
                request_id=request_id,
            )

        # 风控复核员不提供新建申请能力
        if agent_type != "risk" and _is_prefill_intent(req.question):
            return _prefill_response(req.question, request_id=request_id)

        # 规则直连：产品枚举意图直接从知识库 YAML 枚全部产品，不走 LLM 规划。
        # 走 LLM 时它可能误选 list_my_applications（只查已申请的产品）。
        if _is_product_enum_intent(req.question):
            return _product_catalog_response(request_id=request_id)

        history = truncate_history(req.chat_history, _MAX_HISTORY_TURNS)
        outcomes = _run_tool_rounds(
            req, user, db, history,
            agent_type=agent_type,
            planner_prompt=planner_prompt_text,
            allowed_tools=allowed_tools,
        )
        missing_notes = _missing_notes(outcomes)

        hits = outcomes_to_hits(outcomes, req.question)
        rendered = [RenderedHit(index=i + 1, hit=hit) for i, hit in enumerate(hits)]

        if rendered:
            answer, refs_raw, model = _generate_answer(
                req, rendered, history, missing_notes, system_prompt=answer_prompt_text
            )
        else:
            answer = fallback_answer(outcomes, missing_notes) or _NO_DATA_MSG
            refs_raw = []
            model = ""

        answer = truncate_answer(answer, config.ASSISTANT_MAX_ANSWER_CHARS)
        references = [
            ReferenceItem(
                **{
                    **ref,
                    "kind": "business" if ref.get("collection") == "business" else "policy",
                }
            )
            for ref in refs_raw
        ]
        actions = _build_actions(outcomes, references, req.question)

        all_ok = all(o.ok for o in outcomes) if outcomes else True
        if references and all_ok:
            confidence = 0.8
        elif references:
            confidence = 0.6
        elif outcomes:
            confidence = 0.35
        else:
            confidence = 0.2

        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.info(
            "assistant.chat 完成 tools=%d ok=%d refs=%d duration_ms=%d request_id=%s",
            len(outcomes),
            sum(1 for o in outcomes if o.ok),
            len(references),
            duration_ms,
            request_id,
        )

        return _response(
            answer,
            confidence=confidence,
            request_id=request_id,
            references=references,
            actions=actions,
            tool_calls=[
                ToolCallTrace(
                    name=o.name,
                    ok=o.ok,
                    latency_ms=o.latency_ms,
                    args=o.args,
                    error=o.error,
                )
                for o in outcomes
            ],
            model=model or (config.LLM_MODEL or ""),
        )
    except Exception as exc:  # noqa: BLE001 — 顶层兜底：任何未预期异常都降级
        duration_ms = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "assistant.chat 顶层异常，降级为兜底回答：%s duration_ms=%d request_id=%s",
            exc,
            duration_ms,
            request_id,
        )
        return _response(
            f"抱歉，本次查询遇到了意外问题，请稍后重试。（request_id={request_id}）",
            confidence=0.0,
            request_id=request_id,
        )


# ---------------------------------------------------------------- 工具轮次


def _run_tool_rounds(
    req: AssistantRequest,
    user: User,
    db: Session,
    history: list[dict[str, str]] | None,
    *,
    agent_type: AgentType,
    planner_prompt: str,
    allowed_tools: frozenset[str],
) -> list[ToolOutcome]:
    outcomes: list[ToolOutcome] = []
    signatures: set[tuple[Any, ...]] = set()
    executed_names: set[str] = set()
    rounds = max(1, config.ASSISTANT_MAX_TOOL_ROUNDS)

    for round_no in range(1, rounds + 1):
        calls = _plan_calls(
            req, history, executed_names,
            agent_type=agent_type,
            planner_prompt=planner_prompt,
            allowed_tools=allowed_tools,
        )
        new_calls = [c for c in calls if _signature(c) not in signatures][:3]
        if not new_calls:
            logger.info(
                "assistant.plan 无新增调用 agent=%s round=%d executed=%s",
                agent_type,
                round_no,
                sorted(executed_names),
            )
            break

        logger.info(
            "assistant.plan 本轮工具 agent=%s round=%d tools=%s",
            agent_type,
            round_no,
            [c.tool for c in new_calls],
        )

        for call in new_calls:
            signatures.add(_signature(call))
            outcome = execute_tool(
                call.tool,
                {
                    "app_id": call.app_id,
                    "status": call.status,
                    "keyword": call.keyword,
                    "product": call.product,
                    "query": call.query,
                    "category": call.category,
                    "profile": call.profile,
                },
                db,
                user,
                timeout=config.ASSISTANT_TOOL_TIMEOUT,
            )
            outcomes.append(outcome)
            if outcome.ok:
                executed_names.add(call.tool)

    return outcomes


def _plan_calls(
    req: AssistantRequest,
    history: list[dict[str, str]] | None,
    executed_names: set[str],
    *,
    agent_type: AgentType,
    planner_prompt: str,
    allowed_tools: frozenset[str],
) -> list[PlannedCall]:
    """LLM 规划工具；LLM 不可用或返回空时退化为规则直连。"""
    prompt = build_planning_prompt(
        req.question,
        app_id=req.app_id,
        product=req.product,
        history=history,
        executed=sorted(executed_names),
        allowed_tools=allowed_tools,
    )
    try:
        plan = get_client().structured(
            prompt=prompt,
            schema=ToolPlan,
            system=planner_prompt,
        )
        calls = _extract_calls(plan, allowed_tools)
        if calls:
            return calls[:3]
        if executed_names:
            return []
        rule_calls = _rule_calls(req, agent_type)
        logger.info(
            "assistant.plan 空规划，降级规则直连 agent=%s tools=%s",
            agent_type,
            [c.tool for c in rule_calls],
        )
        return rule_calls
    except Exception as exc:  # noqa: BLE001 — 规划失败不得中断问答
        logger.warning("assistant.plan 失败，降级为规则直连：%s", exc)
        return _rule_calls(req, agent_type)


def _extract_calls(plan: Any, allowed_tools: frozenset[str]) -> list[PlannedCall]:
    raw_calls = getattr(plan, "calls", None)
    if raw_calls is None and isinstance(plan, dict):
        raw_calls = plan.get("calls")
    calls: list[PlannedCall] = []
    for item in raw_calls or []:
        if isinstance(item, PlannedCall):
            call = item
        elif isinstance(item, dict):
            try:
                call = PlannedCall(**item)
            except Exception:  # noqa: BLE001
                continue
        else:
            continue
        if call.tool in allowed_tools and call.tool in TOOL_NAMES:
            calls.append(call)
    return calls


def _rule_calls(req: AssistantRequest, agent_type: AgentType) -> list[PlannedCall]:
    """规则直连：按 app_id / 申请编号 / 产品 / 意图关键词选择工具。

    风控复核员与客户经理使用不同的规则直连策略：
    - 风控：无 app_id 时默认查复核队列，不提供材料/准入/本人待办类工具
    - 经理：维持原有流程导向策略
    """
    question = req.question.strip()

    if req.app_id:
        return [
            PlannedCall(tool="get_application_detail", app_id=req.app_id),
            PlannedCall(tool="get_precheck_summary", app_id=req.app_id),
        ]

    matched = _APP_NO_RE.search(question)
    product = _detect_product(question) or req.product

    if agent_type == "risk":
        # 风控复核场景：风险信号 / 冲突 / 存疑 / 通过率 → get_precheck_summary
        if any(term in question for term in (
            "风险", "冲突", "存疑", "不一致", "通过率", "预审结论", "预审结果",
        )):
            if matched:
                return [
                    PlannedCall(tool="list_review_queue"),
                ]
            return [PlannedCall(tool="list_review_queue")]

        if any(term in question for term in (
            "复核队列", "待复核", "要复核", "复核哪些", "今天复核",
        )):
            return [PlannedCall(tool="list_review_queue")]

        if _is_policy_question(question):
            return [PlannedCall(tool="search_policy", query=question, product=product)]

        if _asks_product_choice(question):
            return [PlannedCall(tool="list_products")]

        # 风控默认：列出待复核队列
        return [PlannedCall(tool="list_review_queue")]

    if matched:
        return [PlannedCall(tool="list_my_applications", keyword=matched.group(0))]

    if _asks_product_choice(question):
        calls = [PlannedCall(tool="list_products")]
        if product:
            calls.append(
                PlannedCall(tool="preview_eligibility", product=product, profile=question)
            )
        return calls

    if _asks_materials(question) and product:
        return [PlannedCall(tool="get_required_materials", product=product)]

    if _asks_eligibility(question) and product:
        return [
            PlannedCall(tool="preview_eligibility", product=product, profile=question)
        ]

    if _asks_todos(question):
        return [PlannedCall(tool="list_my_todos")]

    if _is_policy_question(question):
        return [PlannedCall(tool="search_policy", query=question, product=product)]

    return [PlannedCall(tool="list_my_applications", status=_detect_status(req.question))]


# 选产品 / 查材料 / 查准入的意图关键词（规则直连用，粗粒度即可）
_PRODUCT_CHOICE_TERMS: tuple[str, ...] = (
    "哪个产品", "哪些产品", "什么产品", "什么贷款", "产品推荐", "适合哪个", "能做哪个",
)
_MATERIAL_TERMS: tuple[str, ...] = (
    "材料清单", "要准备", "需要哪些材料", "需要什么材料", "哪些材料", "什么材料", "材料要求",
)
_ELIGIBILITY_TERMS: tuple[str, ...] = (
    "准入", "能不能", "能做", "可以做", "能申请", "可以申请",
    "符合条件", "符合吗", "是否满足", "够不够", "能不能过",
)
_TODO_TERMS: tuple[str, ...] = ("待办", "要处理", "这周要", "需要我处理", "优先处理")


def _asks_product_choice(question: str) -> bool:
    return any(term in question for term in _PRODUCT_CHOICE_TERMS)


def _asks_materials(question: str) -> bool:
    return any(term in question for term in _MATERIAL_TERMS)


def _asks_eligibility(question: str) -> bool:
    return any(term in question for term in _ELIGIBILITY_TERMS)


def _asks_todos(question: str) -> bool:
    return any(term in question for term in _TODO_TERMS)


def _is_policy_question(question: str) -> bool:
    """纯政策/规则问句：命中规则编号或政策特征词。"""
    if RULE_ID_RE.search(question):
        return True
    return any(term in question for term in _POLICY_TERMS)


def _detect_product(question: str) -> str | None:
    """从问题中识别产品中文名（长别名优先，避免「快贷」误命中）。"""
    best: tuple[int, str] | None = None
    for name, aliases in PRODUCT_ALIASES.items():
        for alias in (name, *aliases):
            if alias and alias in question:
                size = len(alias)
                if best is None or size > best[0]:
                    best = (size, name)
    return best[1] if best else None


# ---------------------------------------------------------------- 新建申请预填


def _is_prefill_intent(question: str) -> bool:
    if not any(term in question for term in _PREFILL_TERMS):
        return False
    # 「新建申请要准备什么材料 / 受什么规则约束」属于咨询，不是预填
    return not (_asks_materials(question) or "规则" in question or "政策" in question)


_PRODUCT_ENUM_TERMS: tuple[str, ...] = (
    "哪些产品", "哪些信贷产品", "全部产品", "所有产品", "产品列表", "产品清单",
    "产品都有", "有什么产品", "有哪些产品", "产品有哪些", "几款产品",
    "有几款信贷", "有几种产品",
)


def _is_product_enum_intent(question: str) -> bool:
    """纯规则：命中产品枚举词表即为产品清单意图，不考虑是否有 app_id。"""
    if any(term in question for term in _PRODUCT_ENUM_TERMS):
        return True
    # 宽匹配："产品" + "有多少 / 有哪 / 列表" 组合
    if "产品" in question and any(term in question for term in ("有多少", "有哪", "全部", "所有", "列表", "清单")):
        return True
    return False


def _product_catalog_response(request_id: str = "") -> AssistantResponse:
    """规则直连：从知识库 YAML 枚全部产品，不走 LLM。"""
    configs = list_rule_configs()
    if not configs:
        return _response(
            "暂未读取到产品准入配置，请联系风控运营团队。",
            confidence=0.0,
            request_id=request_id,
        )

    feature_map: dict[str, str] = {
        "普惠小微经营贷": "常规经营周转授信，财务报表三表齐全，经营数据可验证",
        "小微快贷": "轻资料快速审批，财务报表可选，流水要求 6 个月",
        "经营性抵押贷": "提供抵押物，可接受负债率更高企业，抵押率上限 70%",
        "科技e贷": "科技型企业专属，有知识产权加分，流水可放宽至 3 个月",
    }

    lines = ["当前在售信贷产品共 4 款：", ""]
    refs: list[ReferenceItem] = []
    for i, config in enumerate(configs, start=1):
        product = str(config.get("product") or "")
        code = str(config.get("product_code") or "")
        feature = feature_map.get(product, "")
        line = f"{i}. **{product}**（产品代码 {code}）— {feature}"
        lines.append(line)
        refs.append(
            ReferenceItem(
                index=i,
                kind="business",
                collection="business",
                source=f"规则配置 rule_{code}_{product}",
                rule_id=None,
                product=product,
                excerpt=f"{product}（{code}）：{feature}",
            )
        )

    return _response(
        "\n".join(lines),
        confidence=0.85,
        request_id=request_id,
        references=refs,
        model="rule-catalog",
    )


def _extract_company_name(question: str) -> str | None:
    """剥离意图词后提取企业全称，避免把「帮我建一笔」并进企业名。"""
    text = question
    for token in (
        "请帮我", "帮我", "麻烦", "我想", "我要",
        "新建申请", "新建一笔", "创建申请", "发起申请", "发起一笔",
        "建一笔", "开一笔", "申请一笔",
    ):
        text = text.replace(token, " ")
    text = re.sub(r"^[\s，,。；;为给]+", "", text)
    match = _COMPANY_RE.search(text)
    return match.group(1).strip() if match else None


def _extract_amount(question: str) -> str | None:
    match = _AMOUNT_CONTEXT_RE.search(question) or _AMOUNT_WAN_RE.search(question)
    if not match:
        return None
    try:
        value = float(match.group(1))
    except ValueError:
        return None
    if value <= 0:
        return None
    return str(int(value)) if value.is_integer() else f"{value:.2f}"


def _prefill_payload(question: str) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    product = _detect_product(question)
    if product:
        payload["product"] = product
    company = _extract_company_name(question)
    if company:
        payload["company_name"] = company
    amount = _extract_amount(question)
    if amount:
        payload["amount"] = amount
    return payload


def _prefill_response(question: str, *, request_id: str) -> AssistantResponse:
    """新建申请意图：只返回 prefill 动作，不调用任何工具、不产生写操作。"""
    payload = _prefill_payload(question)
    if not payload:
        return _response(
            "请告诉我企业名称、贷款金额和产品，例如：帮我为杭州示例科技有限公司"
            "新建一笔 100 万的普惠小微经营贷。我只会预填弹窗，不会自动提交。",
            confidence=0.3,
            request_id=request_id,
        )

    parts: list[str] = []
    if payload.get("company_name"):
        parts.append(f"企业名称「{payload['company_name']}」")
    if payload.get("amount"):
        parts.append(f"贷款金额 {payload['amount']} 万元")
    if payload.get("product"):
        parts.append(f"贷款类型「{payload['product']}」")
    answer = (
        "已为你预填新建申请弹窗：" + "、".join(parts) + "。"
        "请补充统一社会信用代码与申请材料后手动提交；助手不会自动创建或提交任何申请。"
    )
    return _response(
        answer,
        confidence=0.9,
        request_id=request_id,
        actions=[
            AssistantAction(
                label="帮你预填新建申请",
                type="prefill_new_app",
                payload=payload,
            )
        ],
    )


def _detect_status(question: str) -> str | None:
    if "补件" in question:
        return "supplement"
    if "人工" in question:
        return "manual"
    if "风控" in question:
        return "risk"
    if "已审批" in question or "审批通过" in question:
        return "approved"
    if "否决" in question or "拒绝" in question:
        return "rejected"
    if "预审" in question:
        return "precheck"
    if "材料检查" in question:
        return "check"
    return None


def _signature(call: PlannedCall) -> tuple[Any, ...]:
    return (
        call.tool,
        call.app_id,
        (call.status or "").strip(),
        (call.keyword or "").strip(),
        (call.product or "").strip(),
        (call.query or "").strip(),
        (call.category or "").strip(),
        (call.profile or "").strip()[:80],
    )


# ---------------------------------------------------------------- 作答


def _generate_answer(
    req: AssistantRequest,
    rendered: Sequence[RenderedHit],
    history: list[dict[str, str]] | None,
    missing_notes: Sequence[str],
    *,
    system_prompt: str,
) -> tuple[str, list[dict[str, Any]], str]:
    prompt = build_answer_prompt(
        req.question,
        rendered,
        app_id=req.app_id,
        product=req.product,
        history=history,
        missing_notes=missing_notes,
    )
    try:
        resp = get_client().chat(
            system=system_prompt,
            user=prompt,
            temperature=config.LLM_TEMPERATURE,
            max_tokens=800,
        )
        raw = (resp.content or "").strip()
        if not raw:
            raise ValueError("LLM 返回空内容")
        answer, refs_raw = validate_and_clean(raw, rendered)
        return answer, refs_raw, resp.model or ""
    except Exception as exc:  # noqa: BLE001 — LLM 失败仍返回工具数据
        logger.warning("assistant.llm 调用失败，回退为业务数据直出：%s", exc)
        outcomes = _outcomes_from_hits(rendered)
        answer = fallback_answer(outcomes, missing_notes)
        answer, refs_raw = validate_and_clean(answer, rendered)
        return answer, refs_raw, ""


def _outcomes_from_hits(rendered: Sequence[RenderedHit]) -> list[ToolOutcome]:
    """把已渲染命中还原为伪 outcome，仅用于 LLM 失败时的兜底文案。"""
    outcomes: list[ToolOutcome] = []
    for item in rendered:
        meta = item.hit.metadata or {}
        outcomes.append(
            ToolOutcome(
                name="business_data",
                ok=True,
                data=item.hit.text,
                refs=[BusinessRef(source=meta.get("source", ""), excerpt=item.hit.text)],
            )
        )
    return outcomes


def _missing_notes(outcomes: Sequence[ToolOutcome]) -> list[str]:
    notes: list[str] = []
    for outcome in outcomes:
        if not outcome.ok:
            notes.append(f"{outcome.name} {outcome.error or '查询失败'}，本次回答可能不完整")
    return notes


# ---------------------------------------------------------------- 动作与响应


def _build_actions(
    outcomes: Sequence[ToolOutcome],
    references: Sequence[ReferenceItem],
    question: str,
) -> list[AssistantAction]:
    """跳转动作：最多 2 条申请深链；纯政策问答追加「查看完整政策问答」。"""
    actions: list[AssistantAction] = []
    seen: set[int] = set()
    for outcome in outcomes:
        if not outcome.ok:
            continue
        for app in outcome.apps:
            app_id = app.get("id")
            if app_id in seen:
                continue
            seen.add(app_id)
            actions.append(
                AssistantAction(
                    label=f"查看申请 {app.get('app_no', '')}".strip(),
                    type="navigate",
                    target=f"/detail/{app_id}",
                )
            )
    actions = actions[:2]

    business_count = sum(1 for ref in references if ref.kind == "business")
    policy_count = sum(1 for ref in references if ref.kind == "policy")
    if business_count == 0 and (policy_count > 0 or _is_policy_question(question)):
        actions.append(
            AssistantAction(
                label="查看完整政策问答",
                type="open_qa",
                payload={"question": question},
            )
        )
    return actions[:3]


def _in_scope(question: str, app_id: int | None) -> bool:
    if app_id:
        return True
    text = question.strip()
    lowered = text.lower()
    if any(term in text for term in _PREFILL_TERMS):
        return True
    for term in (*_DOMAIN_TERMS, *_ASSISTANT_TERMS):
        if term in text or term.lower() in lowered:
            return True
    return False


def _response(
    answer: str,
    *,
    confidence: float,
    request_id: str,
    references: list[ReferenceItem] | None = None,
    actions: list[AssistantAction] | None = None,
    tool_calls: list[ToolCallTrace] | None = None,
    model: str = "",
) -> AssistantResponse:
    return AssistantResponse(
        answer=answer,
        references=references or [],
        actions=actions or [],
        tool_calls=tool_calls or [],
        confidence=confidence,
        model=model or (config.LLM_MODEL or ""),
        request_id=request_id,
    )
