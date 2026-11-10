"""统一对话入口的请求/响应 Schema。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

from app.assistant.schemas import AssistantResponse
from app.qa.schemas import QaMessage, QaResponse


class ChatRequest(BaseModel):
    """统一入口单轮对话请求：字段为两个子能力的并集。"""

    question: str = Field(..., min_length=1, max_length=500, description="用户问题")
    app_id: int | None = Field(None, ge=1, description="当前详情页的申请主键（服务端仍会校验归属）")
    product: str | None = Field(None, max_length=50, description="产品上下文（可选）")
    category: str | None = Field(None, max_length=50, description="材料类别上下文（可选）")
    chat_history: list[QaMessage] | None = Field(None, description="最近对话历史，服务端自动截断")


class ChatResponse(BaseModel):
    """统一入口响应：route 标识实际使用的能力，仅填充对应字段。"""

    route: Literal["qa", "assistant"] = Field(..., description="分流结果")
    qa: QaResponse | None = Field(None, description="route=qa 时的政策问答结果")
    assistant: AssistantResponse | None = Field(None, description="route=assistant 时的授信助手结果")
