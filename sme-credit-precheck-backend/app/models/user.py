from sqlalchemy import Boolean, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base_class import Base
from app.models.enums import UserRole, enum_column
from app.models.mixins import TimestampMixin


class User(Base, TimestampMixin):
    """系统用户表（客户经理 / 风控人员）。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    full_name: Mapped[str] = mapped_column(String(50))
    role: Mapped[UserRole] = mapped_column(enum_column(UserRole), default=UserRole.MANAGER)
    hashed_password: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
