"""LLM + RAG 框架单元测试。

验证 app/llm/ 和 app/rag/ 封装层的契约：
- factory 单例
- StubClient 回退行为
- InMemoryStore 增删查 + cosine 相似度
"""

from __future__ import annotations

import pytest

from app.llm.base import LLMResponse
from app.llm.factory import get_client
from app.llm.recording import RecordingLLMClient
from app.llm.retry import with_retry
from app.llm.stub_client import StubClient
from app.rag.base import Document
from app.rag.factory import get_vector_store
from app.rag.memory_store import InMemoryStore


# ====================================================================
# LLM
# ====================================================================


class TestLLMFactory:
    def test_get_client_returns_singleton(self) -> None:
        assert get_client() is get_client()


class TestStubClient:
    @pytest.fixture
    def stub(self) -> StubClient:
        return StubClient()

    def test_chat_returns_response(self, stub: StubClient) -> None:
        resp = stub.chat(user="hi")
        assert isinstance(resp, LLMResponse)
        assert resp.content.startswith("[stub]")
        assert resp.usage is not None
        assert resp.usage["total_tokens"] == 0

    def test_chat_structure_valid(self, stub: StubClient) -> None:
        from pydantic import BaseModel

        class Out(BaseModel):
            ok: bool = False

        result = stub.structured(prompt="hi", schema=Out)
        assert isinstance(result, Out)
        assert hasattr(result, "ok")

    def test_embed_returns_zero_vectors(self, stub: StubClient) -> None:
        from app.core import config

        dim = config.EMBEDDING_DIMENSIONS
        vecs = stub.embed(["a", "b"])
        assert len(vecs) == 2
        assert all(len(v) == dim for v in vecs)
        assert all(v == [0.0] * dim for v in vecs)

    def test_embed_handles_empty_list(self, stub: StubClient) -> None:
        assert stub.embed([]) == []


class TestRecordingLLMClient:
    """RecordingLLMClient 包装器：调用成功/失败都应写入 llm_runs。"""

    def test_recording_wrapper_wraps_stub(self) -> None:
        client = RecordingLLMClient(StubClient())
        # 调用应成功，内部写库失败不影响返回
        resp = client.chat(user="test")
        assert resp.content.startswith("[stub]")

    def test_recording_wrapper_propagates_exceptions(self) -> None:
        class FailingClient(StubClient):
            def chat(self, **kwargs):
                raise RuntimeError("API down")

        client = RecordingLLMClient(FailingClient())
        with pytest.raises(RuntimeError, match="API down"):
            client.chat(user="x")

    def test_recording_wrapper_records_success(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """验证 _write_run 在成功时被调用，参数正确。"""
        captured: list[dict] = []

        def fake_write(**kwargs):
            captured.append(kwargs)

        import app.llm.recording as rec

        monkeypatch.setattr(rec, "_write_run", fake_write)

        client = RecordingLLMClient(StubClient())
        client.chat(user="hi")

        assert len(captured) == 1
        assert captured[0]["method"] == "chat"
        assert captured[0]["status"] == "success"
        assert captured[0]["latency_ms"] >= 0

    def test_recording_wrapper_records_failure(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: list[dict] = []

        def fake_write(**kwargs):
            captured.append(kwargs)

        class BoomClient(StubClient):
            def chat(self, **kwargs):
                raise ValueError("boom")

        import app.llm.recording as rec

        monkeypatch.setattr(rec, "_write_run", fake_write)

        client = RecordingLLMClient(BoomClient())
        with pytest.raises(ValueError):
            client.chat(user="x")

        assert captured[0]["status"] == "failure"
        assert "boom" in captured[0]["error_message"]


class TestWithRetry:
    """with_retry 重试逻辑测试。"""

    def test_success_no_retry(self) -> None:
        calls = [0]

        def fn():
            calls[0] += 1
            return "ok"

        result = with_retry(fn, operation="test")
        assert result == "ok"
        assert calls[0] == 1  # 只调用一次

    def test_retry_then_succeed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """第一次抛可重试异常，第二次成功。"""
        import app.llm.retry as retry_mod

        monkeypatch.setattr(retry_mod.time, "sleep", lambda _: None)  # 跳过真实睡眠

        calls = [0]

        def fn():
            calls[0] += 1
            if calls[0] == 1:
                raise ConnectionError("network down")
            return "recovered"

        result = with_retry(fn, operation="test", max_retries=2, base_delay=0.01)
        assert result == "recovered"
        assert calls[0] == 2

    def test_non_retryable_error_raises_immediately(self) -> None:
        """非重试异常（如 ValueError）应立即抛出，不重试。"""
        calls = [0]

        def fn():
            calls[0] += 1
            raise ValueError("bad input")

        with pytest.raises(ValueError, match="bad input"):
            with_retry(fn, operation="test", max_retries=3, base_delay=0.01)

        assert calls[0] == 1  # 只调用一次就抛出

    def test_exhausted_retries_raises_last_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """超过最大重试次数后抛出最后一次异常。"""
        import app.llm.retry as retry_mod

        monkeypatch.setattr(retry_mod.time, "sleep", lambda _: None)

        calls = [0]

        def fn():
            calls[0] += 1
            raise ConnectionError("always down")

        with pytest.raises(ConnectionError, match="always down"):
            with_retry(fn, operation="test", max_retries=2, base_delay=0.01)

        # 首次 + 2 次重试 = 3 次调用
        assert calls[0] == 3

    def test_exponential_backoff_timing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """验证退避时间呈指数增长：base * 2^0, base * 2^1, ..."""
        import app.llm.retry as retry_mod

        delays: list[float] = []
        monkeypatch.setattr(retry_mod.time, "sleep", lambda d: delays.append(d))

        calls = [0]

        def fn():
            calls[0] += 1
            raise ConnectionError("down")

        with pytest.raises(ConnectionError):
            with_retry(fn, operation="test", max_retries=3, base_delay=2)

        # 3 次重试对应 3 次 sleep：2, 4, 8
        assert delays == [2.0, 4.0, 8.0]

    def test_status_code_429_is_retryable(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """HTTP 429 限流应被重试。"""
        import app.llm.retry as retry_mod

        monkeypatch.setattr(retry_mod.time, "sleep", lambda _: None)

        calls = [0]

        class RateLimitErr(Exception):
            status_code = 429

        def fn():
            calls[0] += 1
            if calls[0] == 1:
                raise RateLimitErr("rate limited")
            return "ok"

        assert with_retry(fn, operation="test", max_retries=2, base_delay=0.01) == "ok"
        assert calls[0] == 2

    def test_status_code_400_not_retryable(self) -> None:
        """HTTP 400 参数错误不应重试。"""
        calls = [0]

        class BadRequestErr(Exception):
            status_code = 400

        def fn():
            calls[0] += 1
            raise BadRequestErr("invalid")

        with pytest.raises(BadRequestErr):
            with_retry(fn, operation="test", max_retries=3, base_delay=0.01)

        assert calls[0] == 1


# ====================================================================
# RAG
# ====================================================================


class TestVectorStoreFactory:
    def test_get_vector_store_returns_singleton(self) -> None:
        assert get_vector_store() is get_vector_store()


class TestInMemoryStore:
    @pytest.fixture
    def store(self) -> InMemoryStore:
        return InMemoryStore()

    def test_upsert_and_query_exact_match(self, store: InMemoryStore) -> None:
        store.upsert([
            Document(id="1", text="经营贷要求", vector=[1.0, 0.0]),
            Document(id="2", text="年报要求", vector=[0.0, 1.0]),
        ])
        results = store.query([1.0, 0.0], top_k=1)
        assert len(results) == 1
        assert results[0].document.id == "1"
        assert results[0].score == pytest.approx(1.0, abs=1e-6)

    def test_query_returns_top_k(self, store: InMemoryStore) -> None:
        docs = [Document(id=str(i), text=f"d{i}", vector=[float(i), 0.0]) for i in range(5)]
        store.upsert(docs)
        results = store.query([1.0, 0.0], top_k=3)
        assert len(results) == 3

    def test_where_filter(self, store: InMemoryStore) -> None:
        store.upsert([
            Document(id="a", text="a", vector=[1, 0], metadata={"type": "rule"}),
            Document(id="b", text="b", vector=[1, 0], metadata={"type": "other"}),
        ])
        results = store.query([1, 0], top_k=10, where={"type": "rule"})
        assert all(r.document.metadata.get("type") == "rule" for r in results)

    def test_delete_removes_document(self, store: InMemoryStore) -> None:
        store.upsert([Document(id="x", text="x", vector=[1, 0])])
        store.delete("x")
        results = store.query([1, 0], top_k=1)
        assert results == []

    def test_collections_management(self, store: InMemoryStore) -> None:
        store.upsert([Document(id="1", text="a", vector=[1, 0])], collection="c1")
        store.upsert([Document(id="2", text="b", vector=[0, 1])], collection="c2")
        assert "c1" in store.list_collections()
        assert "c2" in store.list_collections()

        # 不同 collection 互不影响
        assert store.query([1, 0], top_k=1, collection="c1")[0].document.id == "1"
        assert store.query([0, 1], top_k=1, collection="c2")[0].document.id == "2"

    def test_query_empty_store_returns_empty(self, store: InMemoryStore) -> None:
        assert store.query([1, 0], top_k=5) == []
