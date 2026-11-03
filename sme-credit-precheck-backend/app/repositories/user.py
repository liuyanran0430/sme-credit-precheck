"""UserRepository：用户数据库读写唯一入口。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.user import User


class UserRepository:
    """User 模型的查询。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    def get_by_username(self, username: str) -> User | None:
        return self.db.scalar(
            select(User).where(User.username == username)
        )

    def get_by_id(self, id_: int) -> User | None:
        return self.db.get(User, id_)
