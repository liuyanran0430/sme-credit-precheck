"""LLM 调用重试：网络异常 / 限流 / 服务端错误时指数退避重试。

可重试异常（白名单）：
- 网络连接类：openai.APIConnectionError / requests.ConnectionError / httpx.ConnectError
- 超时类：openai.APITimeoutError / requests.Timeout / httpx.TimeoutException
- 限流：openai.RateLimitError（HTTP 429）
- 服务端错误：openai.InternalServerError（HTTP 5xx）

不可重试（直接抛出）：
- 鉴权失败（401/403）
- 参数错误（400）
- 其他业务异常
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from typing import TypeVar

from app.core import config

logger = logging.getLogger(__name__)

T = TypeVar("T")


def _is_retryable(exc: BaseException) -> bool:
    """判断异常是否属于可重试的瞬时错误。"""
    # Python 内置网络/超时异常
    if isinstance(exc, (ConnectionError, TimeoutError, ConnectionResetError, ConnectionRefusedError)):
        return True

    # openai SDK 异常（langchain_openai 底层用 openai）
    try:
        import openai

        retryable_openai = (
            openai.APIConnectionError,
            openai.APITimeoutError,
            openai.RateLimitError,
            openai.InternalServerError,
        )
        if isinstance(exc, retryable_openai):
            return True
    except ImportError:
        pass

    # requests 异常
    try:
        import requests

        if isinstance(exc, (requests.ConnectionError, requests.Timeout)):
            return True
    except ImportError:
        pass

    # httpx 异常
    try:
        import httpx

        if isinstance(exc, (httpx.ConnectError, httpx.TimeoutException, httpx.RemoteProtocolError)):
            return True
    except ImportError:
        pass

    # 兜底：HTTP 状态码判断（部分 SDK 把错误包进通用异常）
    status = getattr(exc, "status_code", None)
    if status is not None and isinstance(status, int):
        if status == 429 or 500 <= status < 600:
            return True

    return False


def with_retry(
    func: Callable[..., T],
    *,
    max_retries: int | None = None,
    base_delay: float | None = None,
    operation: str = "llm_call",
) -> T:
    """执行 func，遇到可重试异常时指数退避后重试。

    参数:
        func: 无参可调用对象（用 lambda 或 partial 传参）
        max_retries: 最大重试次数，默认读 config.LLM_MAX_RETRIES
        base_delay: 首次退避秒数，默认读 config.LLM_RETRY_BASE_DELAY
        operation: 日志里标识的操作名

    返回:
        func 的返回值

    异常:
        超过最大重试次数后，抛出最后一次的异常
    """
    max_retries = config.LLM_MAX_RETRIES if max_retries is None else max_retries
    base_delay = config.LLM_RETRY_BASE_DELAY if base_delay is None else base_delay

    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 — 按白名单判断是否重试
            last_exc = exc
            if not _is_retryable(exc) or attempt >= max_retries:
                raise

            delay = base_delay * (2 ** attempt)  # 指数退避：2s → 4s → 8s ...
            logger.warning(
                "LLM 调用 [%s] 第 %d/%d 次失败，%.1fs 后重试: %s",
                operation,
                attempt + 1,
                max_retries,
                delay,
                exc,
            )
            time.sleep(delay)

    # 理论上不会走到这里（上面 raise 了），保险起见
    assert last_exc is not None
    raise last_exc
