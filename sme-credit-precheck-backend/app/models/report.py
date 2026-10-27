from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, JSON, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.models.enums import AiConclusion, enum_column
from app.models.mixins import TimestampMixin


class AiReport(Base, TimestampMixin):
    """AI 预审报告表。"""

    __tablename__ = "ai_reports"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    app_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[str] = mapped_column(String(16), default="v1", comment="报告版本")
    rule_version: Mapped[str | None] = mapped_column(String(32), nullable=True, comment="规则版本")
    conclusion: Mapped[AiConclusion] = mapped_column(enum_column(AiConclusion))
    summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="预审结论摘要")
    pass_rate: Mapped[Decimal | None] = mapped_column(
        Numeric(5, 2), nullable=True, comment="预估通过率（%）"
    )
    rule_results: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, comment="准入规则逐条匹配结果"
    )
    risk_signals: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, comment="风险信号汇总"
    )
    conflicts: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, comment="低置信/冲突项"
    )
    completeness: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="材料完整性分析结果"
    )
    consistency: Mapped[dict[str, Any] | None] = mapped_column(
        JSON, nullable=True, comment="材料一致性分析结果"
    )
