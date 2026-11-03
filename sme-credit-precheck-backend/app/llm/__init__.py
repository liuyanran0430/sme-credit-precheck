"""LLM 调用封装层。

设计原则：
- 提供统一的 :class:`LLMClient` 抽象基类，上层（classifier / analyzer 等业务服务）只依赖它
- 默认实现 :class:`LangChainClient` 封装 LangChain ChatOpenAI（支持所有 OpenAI 兼容接口：
  OpenAI 原生、Ollama、OpenRouter、DashScope 等）
- 未配置 API Key 时自动 fallback 到 :class:`StubClient`，返回确定性假结果，不阻塞本地开发
- Embedding 统一通过 :meth:`LLMClient.embed` 返回向量

调用流程：
1. `from app.llm import get_client`
2. `client = get_client()`（单例，全项目共用）
3. `client.chat(system=..., user=...)` / `client.structured(prompt, schema)` / `client.embed(texts)`

上层迁移方向（**后续逐步迁移，本次不改现有 services**）：
- services/classifier.py → 把裸 `ChatOpenAI(...)` 替换成 `get_client().chat(...)`
- services/analyzer.py → 同理
- 好处：换模型提供商（OpenAI→Ollama→DashScope）只改 .env 一行，不动业务代码
"""

from .base import LLMClient, LLMResponse
from .langchain_client import LangChainClient
from .stub_client import StubClient
from .factory import get_client, get_embedding_client
from .retry import with_retry

__all__ = [
    "LLMClient",
    "LLMResponse",
    "LangChainClient",
    "StubClient",
    "get_client",
    "get_embedding_client",
    "with_retry",
]
