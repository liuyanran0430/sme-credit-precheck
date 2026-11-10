"""授信助手 Agent 的请求/响应 Schema。"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

from app.qa.schemas import QaMessage, ReferenceItem


class AssistantRequest(BaseModel):
    """单轮对话请求。"""

    question: str = Field(..., min_length=1, max_length=500, description="用户问题")
    app_id: int | None = Field(None, ge=1, description="当前详情页的申请主键（服务端仍会校验归属）")
    product: str | None = Field(None, max_length=50, description="产品上下文（可选）")
    category: str | None = Field(None, max_length=50, description="材料类别上下文（可选）")
    chat_history: list[QaMessage] | None = Field(None, description="最近对话历史，服务端自动截断")


class AssistantAction(BaseModel):
    """回答中的动作按钮，只做跳转或预填，不直接执行业务写操作。"""

    label: str = Field(..., max_length=50)
    type: Literal["navigate", "open_qa", "prefill_new_app"] = Field(..., description="动作类型")
    target: str | None = Field(None, description="navigate 的目标路由")
    payload: dict[str, Any] | None = Field(None, description="open_qa / prefill_new_app 的负载")


class ToolCallTrace(BaseModel):
    """一次工具调用轨迹（脱敏后的参数摘要）。"""

    name: str
    ok: bool
    latency_ms: int = Field(0, ge=0)
    args: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None


class AssistantResponse(BaseModel):
    """单轮对话响应。"""

    answer: str
    references: list[ReferenceItem] = Field(default_factory=list)
    actions: list[AssistantAction] = Field(default_factory=list)
    tool_calls: list[ToolCallTrace] = Field(default_factory=list)
    confidence: float = Field(..., ge=0.0, le=1.0)
    model: str = ""
    request_id: str = ""
