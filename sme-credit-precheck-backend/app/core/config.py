"""应用配置（统一从 .env / 环境变量读取，不在代码中硬编码业务默认值）。"""

import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录下的 .env 文件路径
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)


def _env(key: str, default: str | None = None) -> str | None:
    """从 .env / 环境变量读取配置，未设置时返回 default。"""
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    value = _env(key)
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


def _env_bool(key: str, default: bool) -> bool:
    value = _env(key)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


# 应用信息
APP_NAME = _env("APP_NAME", "小微企业授信智能预审系统")
API_V1_PREFIX = _env("API_V1_PREFIX", "/api/v1")
DEBUG = _env_bool("DEBUG", True)

# 数据库连接
DATABASE_URL = _env("DATABASE_URL", "")
DB_POOL_SIZE = _env_int("DB_POOL_SIZE", 10)
DB_MAX_OVERFLOW = _env_int("DB_MAX_OVERFLOW", 20)
DB_POOL_RECYCLE = _env_int("DB_POOL_RECYCLE", 3600)

# 材料上传
UPLOAD_DIR = _env("UPLOAD_DIR", "uploads")
MAX_UPLOAD_SIZE_MB = _env_int("MAX_UPLOAD_SIZE_MB", 20)

# 跨域（逗号分隔）
CORS_ORIGINS = _env("CORS_ORIGINS", "")

# 登录认证
AUTH_SECRET_KEY = _env("AUTH_SECRET_KEY", "")
AUTH_TOKEN_EXPIRE_MINUTES = _env_int("AUTH_TOKEN_EXPIRE_MINUTES", 480)


def cors_origin_list() -> list[str]:
    """将逗号分隔的 CORS_ORIGINS 拆分为列表。"""
    return [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]
