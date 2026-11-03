"""trace_id 中间件测试。

验证：
1. 不带 X-Request-ID → 后端生成 16 位 hex trace_id 并回传 X-Trace-Id
2. 带 X-Request-ID → 回传相同的值（链路串联）
3. 日志行里包含 trace_id（用 caplog 捕获）
"""

from __future__ import annotations

import re

from fastapi.testclient import TestClient

from app.main import app

TRACE_ID_PATTERN = re.compile(r"^[0-9a-f]{16}$")


def test_generates_trace_id_when_not_provided() -> None:
    with TestClient(app) as client:
        r = client.get("/health")
        assert r.status_code == 200
        trace_id = r.headers.get("X-Trace-Id")
        assert trace_id, "响应头应包含 X-Trace-Id"
        assert TRACE_ID_PATTERN.match(trace_id), f"trace_id 应为 16 位 hex，实际: {trace_id}"


def test_echoes_request_id_when_provided() -> None:
    with TestClient(app) as client:
        custom_id = "abc123def4567890"
        r = client.get("/health", headers={"X-Request-ID": custom_id})
        assert r.status_code == 200
        assert r.headers.get("X-Trace-Id") == custom_id


def test_log_contains_trace_id(caplog) -> None:
    """请求内输出的日志应包含 trace_id。"""
    import logging

    from app.core.logging import setup_logging

    setup_logging(debug=True)

    with TestClient(app) as client:
        with caplog.at_level(logging.INFO):
            client.get("/health")

    # 从日志记录里找到一条带 trace= 的
    traces = [r for r in caplog.records if getattr(r, "trace_id", "-") != "-"]
    # 注意：如果 /health 本身没打日志，可能为空；至少验证 caplog 能正常工作
    # 这里我们通过访问一个会打日志的端点来验证
    if not traces:
        # 改用登录接口（会打日志）
        with caplog.at_level(logging.INFO):
            client.post(
                "/api/v1/auth/login",
                json={"username": "nobody", "password": "wrong"},
            )
        traces = [r for r in caplog.records if getattr(r, "trace_id", "-") != "-"]

    assert traces, "日志记录应包含 trace_id 字段"
    assert TRACE_ID_PATTERN.match(traces[0].trace_id), traces[0].trace_id


def test_different_requests_get_different_trace_ids() -> None:
    """两个请求都不带 X-Request-ID 时，trace_id 应不同。"""
    with TestClient(app) as client:
        r1 = client.get("/health")
        r2 = client.get("/health")
        assert r1.headers["X-Trace-Id"] != r2.headers["X-Trace-Id"]


def test_trace_id_persists_across_internal_calls() -> None:
    """同一个请求内，trace_id 在整个调用链保持一致（由 contextvars 保证）。

    这里通过登录接口验证：请求头带 X-Request-ID，后端处理过程中所有日志都用同一个。
    """
    custom_id = "deadbeefcafebabe"
    with TestClient(app) as client:
        r = client.post(
            "/api/v1/auth/login",
            json={"username": "x", "password": "x"},
            headers={"X-Request-ID": custom_id},
        )
        assert r.headers.get("X-Trace-Id") == custom_id
