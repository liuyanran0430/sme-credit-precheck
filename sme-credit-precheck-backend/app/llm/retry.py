"""LLM 调用重试：按错误类型分级处理。

错误类型与策略（对齐需求表格）：
┌──────────────────────┬────────────────────┬─────────────────────────────┐
│ 问题                  │ 表现                │ 处理策略                     │
├──────────────────────┼────────────────────┼─────────────────────────────┤
│ 429 限流              │ 供应商拒绝请求      │ 指数退避重试（1s / 2s / 4s） │
│ 超时                  │ 响应迟迟不返回      │ LLM_TIMEOUT 硬超时 + 重试上限│
│ 上下文超限            │ Prompt 过长被拒     │ 截断提示词 + max_tokens 上限│
│ JSON 解析失败          │ 模型输出不合规      │ 重试一次后降级转人工          │
└──────────────────────┴────────────────────┴─────────────────────────────┘

可重试异常（白名单）：
- 网络连接类：openai.APIConnectionError / requests.ConnectionError / httpx.ConnectError
- 超时类：openai.APITimeoutError / requests.Timeout / httpx.TimeoutException
- 限流：openai.RateLimitError（HTTP 429）→ 指数退避
- 服务端错误：openai.InternalServerError（HTTP 5xx）

不可重试（直接抛出）：
- 鉴权失败（401/403）
- 参数错误（400）
- 上下文超限（需要截断后重试，见 truncate_and_retry）
- JSON 解析失败（需要重试一次后降级，见 structured 调用点）
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


class LLMTimingError(Exception):
    """LLM 超时异常：表示供应商在硬超时内未返回响应。"""


class LLMContextError(Exception):
    """上下文超限异常：表示 Prompt 超过供应商允许的最大 token 数。"""


class LLMJSONParseError(Exception):
    """JSON 解析失败异常：表示模型输出不是合法 JSON / 不匹配 schema。"""


# ------------------------------------------------------------------
# 错误识别
# ------------------------------------------------------------------


def _is_timeout(exc: BaseException) -> bool:
    """识别是否为超时类错误。"""
    if isinstance(exc, TimeoutError):
        return True

    try:
        import openai

        if isinstance(exc, openai.APITimeoutError):
            return True
    except ImportError:
        pass

    try:
        import requests

        if isinstance(exc, requests.Timeout):
            return True
    except ImportError:
        pass

    try:
        import httpx

        if isinstance(exc, httpx.TimeoutException):
            return True
    except ImportError:
        pass

    return False


def _is_rate_limited(exc: BaseException) -> bool:
    """识别是否为 429 限流。"""
    try:
        import openai

        if isinstance(exc, openai.RateLimitError):
            return True
    except ImportError:
        pass

    status = getattr(exc, "status_code", None)
    if status == 429:
        return True

    msg = str(exc).lower()
    if "rate limit" in msg or "rate_limit" in msg or "too many requests" in msg:
        return True

    return False


def _is_context_overflow(exc: BaseException) -> bool:
    """识别是否为上下文超限错误。

    OpenAI / DashScope / 通义等供应商会返回包含以下关键字的错误：
    - context_length_exceeded
    - maximum context length
    - input tokens length
    - max_tokens
    """
    msg = str(exc).lower()
    keywords = (
        "context_length_exceeded",
        "context length",
        "maximum context",
        "max context",
        "input tokens length",
        "prompt is too long",
        "token limit",
    )
    if any(kw in msg for kw in keywords):
        return True

    # BadRequestError 通常会携带该错误类型
    try:
        import openai

        if isinstance(exc, openai.BadRequestError) and "context" in msg:
            return True
    except ImportError:
        pass

    status = getattr(exc, "status_code", None)
    if status == 400 and any(kw in msg for kw in ("context", "token", "prompt")):
        return True

    return False


def _is_json_parse_error(exc: BaseException) -> bool:
    """识别是否为 JSON 解析失败 / 结构化输出不匹配。"""
    # LangChain with_structured_output 会抛出 OutputParserException / ValueError
    try:
        from langchain_core.exceptions import OutputParserException

        if isinstance(exc, OutputParserException):
            return True
    except ImportError:
        # 兜底：旧版 langchain_core 可能在不同位置
        pass

    msg = str(exc).lower()
    json_keywords = (
        "json",
        "jsondecode",
        "parse",
        "validation error",
        "pydantic",
        "expected value",
        "unterminated",
        "trailing data",
        "extra data",
        "expecting value",
    )
    if any(kw in msg for kw in json_keywords):
        return True

    return False


def _is_retryable(exc: BaseException) -> bool:
    """判断异常是否属于可重试的瞬时错误（429 / 网络 / 超时 / 5xx）。

    上下文超限和 JSON 解析失败不归入此处，由上层专门处理。
    """
    # 上下文超限 → 不归入通用重试，需要截断后再试
    if _is_context_overflow(exc):
        return False

    # JSON 解析失败 → 不归入通用重试，单独处理
    if _is_json_parse_error(exc):
        return False

    # 429 限流 → 归入可重试（指数退避）
    if _is_rate_limited(exc):
        return True

    # 超时 → 归入可重试
    if _is_timeout(exc):
        return True

    # Python 内置网络异常
    if isinstance(exc, (ConnectionError, ConnectionResetError, ConnectionRefusedError)):
        return True

    # openai SDK 服务端错误
    try:
        import openai

        if isinstance(exc, (openai.APIConnectionError, openai.InternalServerError)):
            return True
    except ImportError:
        pass

    # requests / httpx 网络异常
    try:
        import requests

        if isinstance(exc, requests.ConnectionError):
            return True
    except ImportError:
        pass

    try:
        import httpx

        if isinstance(exc, (httpx.ConnectError, httpx.RemoteProtocolError)):
            return True
    except ImportError:
        pass

    # 兜底：HTTP 状态码
    status = getattr(exc, "status_code", None)
    if status is not None and isinstance(status, int):
        if 500 <= status < 600:
            return True

    return False


# ------------------------------------------------------------------
# 重试装饰器
# ------------------------------------------------------------------


def with_retry(
    func: Callable[..., T],
    *,
    max_retries: int | None = None,
    base_delay: float | None = None,
    operation: str = "llm_call",
) -> T:
    """执行 func，遇到可重试异常时指数退避后重试。

    策略：
    - 429 限流 / 5xx / 网络异常 → 指数退避（1s / 2s / 4s / ...）
    - 超时 → 同样指数退避，但总次数受 LLM_MAX_RETRIES 限制
    - 上下文超限 / JSON 解析失败 / 参数错误 → 不在这里重试，抛出给上层

    参数:
        func: 无参可调用对象（用 lambda 或 partial 传参）
        max_retries: 最大重试次数，默认读 config.LLM_MAX_RETRIES
        base_delay: 首次退避秒数，默认读 config.LLM_RETRY_BASE_DELAY（1.0s）
        operation: 日志里标识的操作名
    """
    max_retries = config.LLM_MAX_RETRIES if max_retries is None else max_retries
    base_delay = config.LLM_RETRY_BASE_DELAY if base_delay is None else base_delay

    last_exc: BaseException | None = None
    for attempt in range(max_retries + 1):
        try:
            return func()
        except Exception as exc:  # noqa: BLE001 — 按白名单判断是否重试
            last_exc = exc

            # 上下文超限 / JSON 解析失败 / 参数错误 → 直接抛出
            if not _is_retryable(exc):
                raise

            # 超过次数上限
            if attempt >= max_retries:
                raise

            # 指数退避：1s → 2s → 4s → 8s ...
            delay = base_delay * (2**attempt)

            if _is_rate_limited(exc):
                logger.warning(
                    "LLM 调用 [%s] 第 %d/%d 次限流 (429)，%.1fs 后重试: %s",
                    operation,
                    attempt + 1,
                    max_retries,
                    delay,
                    exc,
                )
            elif _is_timeout(exc):
                logger.warning(
                    "LLM 调用 [%s] 第 %d/%d 次超时，%.1fs 后重试: %s",
                    operation,
                    attempt + 1,
                    max_retries,
                    delay,
                    exc,
                )
            else:
                logger.warning(
                    "LLM 调用 [%s] 第 %d/%d 次网络失败，%.1fs 后重试: %s",
                    operation,
                    attempt + 1,
                    max_retries,
                    delay,
                    exc,
                )

            time.sleep(delay)

    assert last_exc is not None
    raise last_exc
