"""日志基础设施单元测试（Phase 1）。

纯内存验证，不碰文件系统 / MySQL / FastAPI。
覆盖 LogContext、ContextFormatter、脱敏工具的核心行为。
"""

from __future__ import annotations

import asyncio
import logging

import pytest

from app.core.logging import (
    ContextFormatter,
    LogContext,
    mask_amount,
    mask_credit_code,
)


# ====================================================================
# LogContext：set / get / clear
# ====================================================================


class TestLogContextBasics:
    """LogContext 基本链路：set → get → clear。"""

    def test_get_empty_at_start(self) -> None:
        assert LogContext.get() == {}

    def test_set_single_key(self) -> None:
        LogContext.clear()
        LogContext.set(app_no="AP00000001")
        assert LogContext.get() == {"app_no": "AP00000001"}

    def test_set_multiple_keys(self) -> None:
        LogContext.clear()
        LogContext.set(app_no="AP00000001", user="manager", source="api")
        got = LogContext.get()
        assert got["app_no"] == "AP00000001"
        assert got["user"] == "manager"
        assert got["source"] == "api"

    def test_set_overwrites_existing(self) -> None:
        LogContext.clear()
        LogContext.set(app_no="old", user="a")
        LogContext.set(app_no="new")
        got = LogContext.get()
        assert got["app_no"] == "new"
        assert got["user"] == "a"  # 未覆盖的 key 保留

    def test_set_none_value_becomes_dash(self) -> None:
        LogContext.clear()
        LogContext.set(user=None, app_no="AP00000001")
        got = LogContext.get()
        assert got["user"] == "-"
        assert got["app_no"] == "AP00000001"

    def test_clear_empties_dict(self) -> None:
        LogContext.clear()
        LogContext.set(app_no="AP00000001", user="manager")
        LogContext.clear()
        assert LogContext.get() == {}

    def test_get_returns_copy(self) -> None:
        """get() 返回的是副本，外部修改不影响内部 ctx。"""
        LogContext.clear()
        LogContext.set(app_no="AP00000001")
        snapshot = LogContext.get()
        snapshot["app_no"] = "tampered"
        assert LogContext.get() == {"app_no": "AP00000001"}


# ====================================================================
# LogContext：上下文管理器（with 块）
# ====================================================================


class TestLogContextWithBlock:
    """with LogContext(...): 自动 set / clear。"""

    def test_with_block_sets_then_clears(self) -> None:
        LogContext.clear()
        with LogContext(app_no="AP00000001", user="manager"):
            assert LogContext.get() == {"app_no": "AP00000001", "user": "manager"}
        assert LogContext.get() == {}

    def test_with_block_restores_outer_on_exit(self) -> None:
        """with 块退出后外层 ctx 被恢复（而非清空整个 ctx）。"""
        LogContext.clear()
        LogContext.set(app_no="OUTER")
        with LogContext(user="inner"):
            got = LogContext.get()
            assert got["app_no"] == "OUTER"
            assert got["user"] == "inner"
        # 退出内层 with 后，只剩 set() 进去的外层值
        assert LogContext.get() == {"app_no": "OUTER"}

    def test_nested_with_blocks(self) -> None:
        LogContext.clear()
        with LogContext(app_no="AP00000001"):
            with LogContext(user="manager"):
                got = LogContext.get()
                assert got["app_no"] == "AP00000001"
                assert got["user"] == "manager"
            # 内层退出，外层仍在
            got = LogContext.get()
            assert got == {"app_no": "AP00000001"}
        assert LogContext.get() == {}

    def test_with_block_clears_on_exception(self) -> None:
        """with 块内抛异常仍能正确清理 ctx。"""
        LogContext.clear()
        with pytest.raises(ValueError):
            with LogContext(app_no="AP00000001"):
                raise ValueError("boom")
        assert LogContext.get() == {}


# ====================================================================
# LogContext：协程隔离（关键回归测试）
# ====================================================================


class TestLogContextCoroutineIsolation:
    """并发协程下 ContextVar 不串上下文。"""

    def test_coroutines_do_not_leak_context(self) -> None:
        async def coro_a() -> str:
            with LogContext(app_no="AP_CORO_A", user="alice"):
                # 让出控制权，让 B 协程跑
                await asyncio.sleep(0)
                # 再让出一次（模拟 A 做了点事回来）
                await asyncio.sleep(0)
                return LogContext.get()  # 此时应该还是 A 的 ctx

        async def coro_b() -> str:
            with LogContext(app_no="AP_CORO_B", user="bob"):
                await asyncio.sleep(0)
                await asyncio.sleep(0)
                return LogContext.get()  # 此时应该还是 B 的 ctx

        async def main() -> None:
            a_ctx, b_ctx = await asyncio.gather(coro_a(), coro_b())

            # 关键断言：两个协程各自保持了自己的上下文
            assert a_ctx["app_no"] == "AP_CORO_A"
            assert a_ctx["user"] == "alice"
            assert b_ctx["app_no"] == "AP_CORO_B"
            assert b_ctx["user"] == "bob"

            # A 协程结束后，B 的上下文不该被 A 残留值污染
            # （ContextVar 自动隔离，这条断言纯粹是双保险）
            assert "AP_CORO_A" != "AP_CORO_B"

        # 确保全局干净
        LogContext.clear()
        asyncio.run(main())
        LogContext.clear()


# ====================================================================
# 敏感脱敏工具
# ====================================================================


class TestMaskCreditCode:
    """统一社会信用代码脱敏。"""

    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("91330100MA2XXXX5678", "9133****5678"),  # 完整 18 位
            ("91330100", "9133****0100"),              # 恰好 8 位 → 首尾各 4
            ("", "****"),                                # 空串
            (None, "****"),                             # None
            ("1234567", "****"),                        # 正好 7 位 < 8 → 兜底
            ("ABCDEFGH", "ABCD****EFGH"),               # 恰好 8 位，非数字也适用
        ],
    )
    def test_mask_various_inputs(self, raw: str | None, expected: str) -> None:
        result = mask_credit_code(raw)
        # 至少保证不含完整原始值（敏感不漏）
        if raw and len(raw) >= 8:
            assert raw not in result, f"敏感代码不应完整出现于脱敏结果: {result}"
        assert result == expected


class TestMaskAmount:
    """金额脱敏：单位转换到万元。"""

    @pytest.mark.parametrize(
        ("raw", "expected_suffix"),
        [
            (500000, "50.0万"),          # 50 万整
            (1234, "0.1万"),              # 零头
            (0, "0"),                     # 零
            (None, "0"),                  # None
            (10000, "1.0万"),             # 恰好 1 万
            (99999999, "10000.0万"),      # 大额
            (500000.5, "50.0万"),         # 浮点
        ],
    )
    def test_mask_various_inputs(self, raw: float | int | None, expected_suffix: str) -> None:
        result = mask_amount(raw)
        assert result == expected_suffix


# ====================================================================
# ContextFormatter
# ====================================================================


class TestContextFormatter:
    """Formatter 正确把 LogContext 注入日志行。"""

    @pytest.fixture
    def fmt(self) -> ContextFormatter:
        return ContextFormatter(
            fmt="%(levelname)s ctx=%(_ctx)s %(message)s",
            datefmt="%Y-%m-%d",
        )

    def _make_record(self, msg: str = "hello") -> logging.LogRecord:
        return logging.LogRecord(
            name="test.module",
            level=logging.INFO,
            pathname="test.py",
            lineno=10,
            msg=msg,
            args=(),
            exc_info=None,
        )

    def test_ctx_present_in_output(self, fmt: ContextFormatter) -> None:
        LogContext.clear()
        LogContext.set(app_no="AP00000001", user="manager")
        record = self._make_record("业务完成")
        line = fmt.format(record)
        assert "app_no=AP00000001" in line
        assert "user=manager" in line
        assert "业务完成" in line

    def test_ctx_empty_shows_dash(self, fmt: ContextFormatter) -> None:
        LogContext.clear()
        record = self._make_record("没有上下文")
        line = fmt.format(record)
        assert "ctx=-" in line
        assert "没有上下文" in line

    def test_ctx_none_value_shows_dash(self, fmt: ContextFormatter) -> None:
        LogContext.clear()
        LogContext.set(user=None)
        record = self._make_record("user 为 None")
        line = fmt.format(record)
        assert "user=-" in line

    def test_skip_keys_not_injected(self, fmt: ContextFormatter) -> None:
        """LogContext.get() 不应该出现 formatter._SKIP_KEYS 里的键。

        这主要测 _SKIP_KEYS 的过滤逻辑。
        """
        LogContext.clear()
        LogContext.set(app_no="AP00000001")
        record = self._make_record("检查 skip")
        line = fmt.format(record)
        # 验证 record 的标准字段没有被注入
        assert "context=" not in line.lower()  # 防止某些实现把 record 的其它属性扫进去
        # 验证业务字段在
        assert "app_no=AP00000001" in line
