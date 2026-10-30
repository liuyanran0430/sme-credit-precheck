from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.models.enums import ApplicationStatus, enum_column
from app.models.mixins import TimestampMixin


class Application(Base, TimestampMixin):
    """授信申请主表。"""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    app_no: Mapped[str] = mapped_column(String(32), unique=True, index=True, comment="申请编号")
    company_name: Mapped[str] = mapped_column(String(200), index=True, comment="企业名称")
    credit_code: Mapped[str | None] = mapped_column(
        String(18), index=True, nullable=True, comment="统一社会信用代码"
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(12, 2), comment="申请金额（万元）")
    product: Mapped[str] = mapped_column(String(100), comment="贷款产品")
    status: Mapped[ApplicationStatus] = mapped_column(
        enum_column(ApplicationStatus), default=ApplicationStatus.CHECK, index=True
    )
    manager_name: Mapped[str | None] = mapped_column(String(50), nullable=True, comment="客户经理")
    sla_deadline: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, comment="时效截止时间"
    )
    ai_summary: Mapped[str | None] = mapped_column(Text, nullable=True, comment="AI 摘要")
    supplement_note: Mapped[str | None] = mapped_column(
        String(500), nullable=True, comment="退回补件说明"
    )
    supplement_source: Mapped[str | None] = mapped_column(
        String(10), nullable=True, comment="补件来源：manual=人工复核退回，risk=风控退回"
    )
