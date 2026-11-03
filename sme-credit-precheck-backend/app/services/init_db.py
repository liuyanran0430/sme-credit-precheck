"""数据库初始化：启动时 create_all 建表。

注意：这是**开发环境快捷入口**，生产环境请统一走 Alembic 迁移。
"""

import logging

from app.models import Base  # 触发 models/__init__.py 执行，确保 Base.metadata 包含全库表
from app.models.session import engine

logger = logging.getLogger(__name__)


def init_db() -> None:
    """按 ORM 模型定义自动建表。"""
    Base.metadata.create_all(bind=engine)
    logger.info("数据库表结构已初始化")
