from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.models.enums import MaterialStatus, enum_column
from app.models.mixins import TimestampMixin


class Material(Base, TimestampMixin):
    """申请材料表。"""

    __tablename__ = "materials"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    app_id: Mapped[int] = mapped_column(
        ForeignKey("applications.id", ondelete="CASCADE"), index=True
    )
    category: Mapped[str] = mapped_column(String(100), comment="材料类别")
    file_name: Mapped[str] = mapped_column(String(255), comment="文件名")
    file_url: Mapped[str | None] = mapped_column(String(500), nullable=True, comment="存储地址")
    file_size: Mapped[int | None] = mapped_column(nullable=True, comment="文件大小（字节）")
    version: Mapped[str] = mapped_column(String(16), default="v1.0", comment="材料版本")
    status: Mapped[MaterialStatus] = mapped_column(
        enum_column(MaterialStatus), default=MaterialStatus.PENDING
    )
    confidence: Mapped[Decimal | None] = mapped_column(
        Numeric(4, 3), nullable=True, comment="AI 分类置信度"
    )
    reason: Mapped[str | None] = mapped_column(Text, nullable=True, comment="AI 分类依据")
    ocr_text: Mapped[str | None] = mapped_column(
        Text, nullable=True, comment="OCR 抽取文本（复用于分类与预审，避免重复识别）"
    )
