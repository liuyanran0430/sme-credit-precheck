from typing import Any

from sqlalchemy import ForeignKey, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.models.enums import ReviewDecision, enum_column
from app.models.mixins import TimestampMixin


class ManualReview(Base, TimestampMixin):
    """人工复核记录表。"""

    __tablename__ = "manual_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    app_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(50), comment="复核人")
    decision: Mapped[ReviewDecision] = mapped_column(enum_column(ReviewDecision))
    checklist_result: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON, nullable=True, comment="逐项复核结果"
    )
    comment: Mapped[str | None] = mapped_column(Text, nullable=True, comment="复核意见")


class RiskReview(Base, TimestampMixin):
    """风控复核记录表。"""

    __tablename__ = "risk_reviews"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    app_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    reviewer: Mapped[str] = mapped_column(String(50), comment="风控人员")
    decision: Mapped[ReviewDecision] = mapped_column(enum_column(ReviewDecision))
    opinion: Mapped[str] = mapped_column(Text, comment="风控复核意见")
    mitigation: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="风险缓释条件")
