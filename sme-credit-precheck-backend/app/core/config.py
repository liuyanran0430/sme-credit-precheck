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

# LLM 调用（OpenAI 兼容接口：Ollama / OpenRouter / DashScope 等均可）
LLM_PROVIDER = _env("LLM_PROVIDER", "langchain-openai")  # 未来可扩展 ollama / dashscope
LLM_API_KEY = _env("LLM_API_KEY", _env("OPENAI_API_KEY", ""))
LLM_BASE_URL = _env("LLM_BASE_URL", _env("OPENAI_BASE_URL", "https://api.openai.com/v1"))
LLM_MODEL = _env("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SECONDS = _env_int("LLM_TIMEOUT_SECONDS", 60)
LLM_TEMPERATURE = float(_env("LLM_TEMPERATURE", "0.1"))
LLM_MAX_RETRIES = _env_int("LLM_MAX_RETRIES", 2)
LLM_RETRY_BASE_DELAY = float(_env("LLM_RETRY_BASE_DELAY", "1"))  # 指数退避首项（秒）：1 → 2 → 4（对齐 429 限流策略）
LLM_PROMPT_VERSION = _env("LLM_PROMPT_VERSION", "v1")  # 当前 Prompt 版本，写入 LLM 结构化日志便于回溯

# Embedding（默认用 LLM 同提供商的 text-embedding API；设为空字符串表示不启用）
EMBEDDING_MODEL = _env("EMBEDDING_MODEL", "")
EMBEDDING_DIMENSIONS = _env_int("EMBEDDING_DIMENSIONS", 1536)

# RAG 向量库
VECTOR_STORE_BACKEND = _env("VECTOR_STORE_BACKEND", "memory")  # memory | chroma | milvus
VECTOR_STORE_PERSIST_DIR = _env("VECTOR_STORE_PERSIST_DIR", "data/chroma")
VECTOR_STORE_COLLECTION = _env("VECTOR_STORE_COLLECTION", "credit_rules")


def cors_origin_list() -> list[str]:
    """将逗号分隔的 CORS_ORIGINS 拆分为列表。"""
    return [origin.strip() for origin in CORS_ORIGINS.split(",") if origin.strip()]
