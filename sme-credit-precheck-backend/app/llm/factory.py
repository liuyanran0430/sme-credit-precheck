"""LLM Client 工厂：根据配置自动选择实现，单例返回。

使用方式：
    from app.llm import get_client, get_embedding_client
    client = get_client()
    resp = client.chat(system="你是一个银行风控专家", user="这是什么材料？")
    embeddings = get_embedding_client().embed(["材料文本 1", "材料文本 2"])

首次调用时根据 :mod:`app.core.config` 中的 LLM_PROVIDER / LLM_API_KEY 决定：
- LangChain 已装 + API Key 非空 → :class:`LangChainClient`（真实调用）
- 否则 → :class:`StubClient`（占位）
"""

from __future__ import annotations

import logging

from app.core import config
from app.llm.base import LLMClient
from app.llm.recording import RecordingLLMClient

logger = logging.getLogger(__name__)

_client: LLMClient | None = None
_embedding_client: LLMClient | None = None


def _has_langchain() -> bool:
    try:
        import langchain_openai  # noqa: F401

        return True
    except ImportError:
        return False


def get_client() -> LLMClient:
    """获取全局共享的 LLM 客户端（单例，已包装调用记录器）。"""
    global _client
    if _client is not None:
        return _client

    if _has_langchain() and config.LLM_API_KEY:
        from app.llm.langchain_client import LangChainClient

        inner = LangChainClient()
    else:
        from app.llm.stub_client import StubClient

        inner = StubClient()

    # 用 RecordingLLMClient 包装，所有调用自动写入 llm_runs 表
    _client = RecordingLLMClient(inner)
    return _client


def get_embedding_client() -> LLMClient:
    """获取全局共享的 embedding 客户端（单例）。

    默认与 chat 共用同一个 LangChainClient（内部 embed 方法独立），
    未来如果有 embedding-only 的模型（如本地 bge-m3）可以拆分。
    """
    return get_client()
