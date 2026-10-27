from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.core import config

# SQLite 需要关闭同线程检查；MySQL 使用连接池并回收长连接
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
