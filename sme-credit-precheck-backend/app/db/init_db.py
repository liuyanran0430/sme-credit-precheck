from app.db.base import Base
from app.db.session import engine


def init_db() -> None:
    """开发环境初始化建表；生产环境请使用 Alembic 迁移。"""
    Base.metadata.create_all(bind=engine)
