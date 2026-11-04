"""LLM 调用记录表：每次 ModelClient 调用记录 model / token / latency / 状态。"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import Float, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base
from app.models.mixins import TimestampMixin


class LLMRun(Base, TimestampMixin):
    """每次 LLM 调用的遥测记录。"""

    __tablename__ = "llm_runs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    model: Mapped[str | None] = mapped_column(String(128), nullable=True, comment="模型名")
    method: Mapped[str] = mapped_column(String(32), comment="调用方法：chat / structured / embed")
    prompt_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    completion_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    total_tokens: Mapped[int | None] = mapped_column(Integer, nullable=True)
    latency_ms: Mapped[float] = mapped_column(Float, comment="调用耗时（毫秒）")
    status: Mapped[str] = mapped_column(String(16), comment="success / failure")
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True, comment="失败时的异常信息")
    request_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, comment="关联的异步任务 request_id（与接口返回给前端的一致）"
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
