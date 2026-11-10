"""数据库初始化：启动时 create_all 建表。

注意：这是**开发环境快捷入口**，生产环境请统一走 Alembic 迁移。
"""

import logging

from sqlalchemy import inspect, text

from app.models import Base  # 触发 models/__init__.py 执行，确保 Base.metadata 包含全库表
from app.models.session import engine

logger = logging.getLogger(__name__)

# 历史库新增列（create_all 不会为已存在的表补列）：表名 → {列名: DDL 类型}
_ADDED_COLUMNS: dict[str, dict[str, str]] = {
    "risk_reviews": {"checklist_result": "JSON"},
}


def _ensure_columns() -> None:
    """为已存在的表补齐后续新增的列（幂等）。"""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table, columns in _ADDED_COLUMNS.items():
            if not insp.has_table(table):
                continue
            existing = {c["name"] for c in insp.get_columns(table)}
            for name, ddl in columns.items():
                if name not in existing:
                    conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}"))
                    logger.info("已为表 %s 补充列 %s", table, name)


def init_db() -> None:
    """按 ORM 模型定义自动建表。"""
    Base.metadata.create_all(bind=engine)
    _ensure_columns()
    logger.info("数据库表结构已初始化")
