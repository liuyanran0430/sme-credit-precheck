"""统一对话入口：按问题自动分流至政策问答 / 授信助手。

分流规则（纯规则，零额外 LLM 调用）：
  1. 带当前申请上下文（app_id）→ 助手（按角色选经理/风控）
  2. 个人化业务问题（「我的申请进度」等）或命中申请编号 / 业务语义 → 助手
  3. 其余 → 政策问答

助手类型按用户角色自动选择：
  - risk → 风控预审助手（偏风险汇总，工具集受限）
  - 其余 → 客户经理授信助手（偏流程与资料准备）
"""

from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from app.assistant.agent import AgentType, chat as assistant_chat
from app.assistant.schemas import AssistantRequest
from app.chat.schemas import ChatRequest, ChatResponse
from app.models.enums import UserRole
from app.models.user import User
from app.qa.schemas import QaRequest
from app.qa.service import ask_question, is_personal_business_question

logger = logging.getLogger(__name__)

# 申请编号（与授信助手工具相同的格式）
_APP_NO_RE = re.compile(r"\b(?:AP|AK|AJ|AE)\d{8}\b")

# 明确的业务办理语义（不含泛化的「状态」「材料」等政策咨询词）
_BUSINESS_TERMS: tuple[str, ...] = (
    "进度", "待办", "补件", "预审报告", "风险信号", "通过率",
    "申请编号", "申请号", "卡在", "我这笔", "这笔申请", "这个申请", "该申请",
    "缺什么", "缺哪些",
    # 风控复核语义：待复核队列相关，走风控预审助手的 list_review_queue 工具
    "待复核", "待我复核", "复核队列", "风控复核", "要复核", "待我审批", "待审批",
    # 风险判断语义：确认风险 / 排除误报类问题，走风控助手结合队列与政策作答
    "确认风险", "误报",
)

# 产品枚举意图：询问"有哪些产品 / 全部产品 / 产品清单"等，
# 这类问题走 assistant 的 list_products 工具能从规则 YAML 枚出完整列表，
# 而走 qa RAG 会受 top_k=3 限制，只能部分覆盖。
_PRODUCT_ENUM_TERMS: tuple[str, ...] = (
    "哪些产品", "哪些信贷产品", "全部产品", "所有产品", "产品列表", "产品清单",
    "产品都有", "有什么产品", "有哪些产品", "产品有哪些", "几款产品",
)


def _should_use_assistant(question: str, app_id: int | None) -> bool:
    if app_id:
        return True
    text = question.strip()
    if is_personal_business_question(text):
        return True
    if _APP_NO_RE.search(text):
        return True
    if any(term in text for term in _BUSINESS_TERMS):
        return True
    if any(term in text for term in _PRODUCT_ENUM_TERMS):
        return True
    return False


def dispatch(
    req: ChatRequest,
    user: User,
    db: Session,
    *,
    request_id: str = "",
) -> ChatResponse:
    """统一入口：返回 route 与实际使用的子能力结果（另一侧为 null）。"""
    try:
        if _should_use_assistant(req.question, req.app_id):
            agent_type: AgentType = (
                "risk" if user.role == UserRole.RISK else "manager"
            )
            response = assistant_chat(
                AssistantRequest(
                    question=req.question,
                    app_id=req.app_id,
                    product=req.product,
                    category=req.category,
                    chat_history=req.chat_history,
                ),
                user,
                db,
                agent_type=agent_type,
                request_id=request_id,
            )
            return ChatResponse(route="assistant", assistant=response)

        response = ask_question(
            QaRequest(
                question=req.question,
                product=req.product,
                category=req.category,
                chat_history=req.chat_history,
            ),
            request_id=request_id,
        )
        return ChatResponse(route="qa", qa=response)
    except Exception:  # noqa: BLE001 — 顶层兜底，保证不抛 500
        logger.exception("chat.dispatch 顶层异常，降级返回 QA 空回答 request_id=%s", request_id)
        # 无论路由原本指向谁，都返回 qa 侧的空回答（qa.response_model 是单一 QaResponse），
        # 前端渲染时 route=qa 会直接展示 answer。
        from app.qa.schemas import QaResponse

        return ChatResponse(
            route="qa",
            qa=QaResponse(
                answer=f"抱歉，本次请求遇到了意外问题，请稍后重试。（request_id={request_id}）",
                references=[],
                confidence=0.0,
                model="",
                request_id=request_id,
            ),
        )
