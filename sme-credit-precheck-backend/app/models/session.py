"""SQLAlchemy 引擎与请求级会话工厂。

职责：把 :mod:`app.core.config` 里的数据库配置值变成真实的 SQLAlchemy 对象。

两套参数（SQLite vs MySQL）：
- SQLite：关闭同线程检查，单文件持久化
- MySQL：连接池（pool_size / max_overflow / pool_recycle）+ pool_pre_ping 自动重连
"""

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import config

if config.DATABASE_URL.startswith("sqlite"):
    engine = create_engine(
        config.DATABASE_URL,
        pool_pre_ping=True,
        connect_args={"check_same_thread": False},
    )
else:
    engine = create_engine(
        config.DATABASE_URL,
        pool_pre_ping=True,
        pool_size=config.DB_POOL_SIZE,
        max_overflow=config.DB_MAX_OVERFLOW,
        pool_recycle=config.DB_POOL_RECYCLE,
    )

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False)
