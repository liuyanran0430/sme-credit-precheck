"""统一日志配置：控制台 + 按天滚动文件，所有模块共享。

用法（任何模块）：
    import logging
    from app.core.logging import LogContext

    logger = logging.getLogger(__name__)

    with LogContext(app_no="AP00000001", user="manager"):
        logger.info("开始 AI 预审, materials=%d", len(materials))

    # 或在 FastAPI 依赖中手动设置上下文
    LogContext.set(app_no="AP00000001", user_id=3)
    try:
        ...
    finally:
        LogContext.clear()
"""

from __future__ import annotations

import contextvars
import logging
import logging.handlers
from datetime import date
from pathlib import Path

# --------------------------- 日志根目录 ---------------------------

_LOGS_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOGS_DIR.mkdir(exist_ok=True)


# --------------------------- 上下文（协程安全，FastAPI async endpoint 专用） ---------------------------

_ctx_var: contextvars.ContextVar[dict[str, object] | None] = contextvars.ContextVar("log_ctx", default=None)


class LogContext:
    """协程本地上下文，为日志自动注入 app_no / user 等业务字段。"""

    @classmethod
    def set(cls, **kwargs: object) -> None:
        cur = _ctx_var.get() or {}
        _ctx_var.set(cur | {k: (v if v is not None else "-") for k, v in kwargs.items()})

    @classmethod
    def get(cls) -> dict[str, object]:
        return dict(_ctx_var.get() or {})

    @classmethod
    def clear(cls) -> None:
        _ctx_var.set(None)

    class _Ctx:
        """上下文管理器版本，方便在 with 块内自动清理。

        支持嵌套：内层 with 退出时恢复进入前的快照，
        不会误伤外层已 set 的上下文。
        """

        def __init__(self, **kwargs: object) -> None:
            self.kwargs = kwargs
            self._snapshot: dict[str, object] | None = None

        def __enter__(self) -> None:
            self._snapshot = LogContext.get()
            LogContext.set(**self.kwargs)

        def __exit__(self, *exc: object) -> None:
            _ctx_var.set(self._snapshot if self._snapshot else None)

    def __call__(self, **kwargs: object) -> LogContext._Ctx:  # type: ignore[no-untyped-call]
        """允许 `with LogContext(app_no=..., user=...):` 这样写。"""
        return self._Ctx(**kwargs)


LogContext = LogContext()  # type: ignore[assignment]


# --------------------------- 格式化 ---------------------------

class ContextFormatter(logging.Formatter):
    """把 LogContext 中的 app_no / user 等自动拼到日志行里。"""

    _SKIP_KEYS = {"thread", "name", "threadName", "msecs", "process", "processName"}

    def format(self, record: logging.LogRecord) -> str:
        extras = LogContext.get()
        # trace_id 单独提取到 record，放在日志行最前面方便 grep
        trace_id = extras.get("trace_id", "-")
        record.trace_id = trace_id  # type: ignore[attr-defined]
        # ctx 部分去掉 trace_id（避免重复），保留 app_no / user 等业务字段
        ctx_extras = {k: v for k, v in extras.items() if k != "trace_id"}
        ctx_parts = [f"{k}={v}" for k, v in ctx_extras.items() if k not in self._SKIP_KEYS]
        ctx_str = " ".join(ctx_parts) if ctx_parts else "-"
        record._ctx = ctx_str  # type: ignore[attr-defined]
        return super().format(record)


# --------------------------- 按天滚动文件 Handler ---------------------------

class DailyRotatingFileHandler(logging.handlers.BaseRotatingHandler):
    """午夜自动切新文件，文件名 `app-YYYY-MM-DD.log`。"""

    def __init__(self, directory: Path, level: int = logging.INFO) -> None:
        self._directory = directory
        self._current_date: date | None = None
        filename = self._filename_for(date.today())
        super().__init__(filename, mode="a", encoding="utf-8")
        self.setLevel(level)

    def _filename_for(self, d: date) -> str:
        return str(self._directory / f"app-{d.isoformat()}.log")

    def shouldRollover(self, record: logging.LogRecord) -> bool:  # noqa: N802
        if self._current_date is None:
            self._current_date = date.today()
            return False
        return date.today() != self._current_date

    def doRollover(self) -> None:  # noqa: N802
        if self.stream:
            self.stream.close()
        self._current_date = date.today()
        self.baseFilename = self._filename_for(self._current_date)
        self.stream = self._open()
        # 简单清理超过 30 天的旧文件
        self._cleanup_old(keep_days=30)

    def _cleanup_old(self, keep_days: int) -> None:
        import time

        now = time.time()
        for f in self._directory.glob("app-*.log"):
            try:
                if (now - f.stat().st_mtime) / 86400 > keep_days:
                    f.unlink(missing_ok=True)
            except OSError:
                pass


# --------------------------- 初始化 ---------------------------

_initialized = False


def setup_logging(debug: bool = False) -> None:
    """全局一次性初始化日志系统，idempotent。"""
    global _initialized
    if _initialized:
        return

    level = logging.DEBUG if debug else logging.INFO
    root = logging.getLogger()
    root.setLevel(level)

    fmt = ContextFormatter(
        fmt="%(asctime)s %(levelname)-7s [%(name)s:%(lineno)d] trace=%(trace_id)s ctx=%(_ctx)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # 控制台
    console = logging.StreamHandler()
    console.setLevel(level)
    console.setFormatter(fmt)
    root.addHandler(console)

    # 按天滚动文件
    try:
        file_handler = DailyRotatingFileHandler(_LOGS_DIR, level=level)
        file_handler.setFormatter(fmt)
        root.addHandler(file_handler)
    except OSError as exc:
        # 日志目录写不了时降级为只控制台
        root.warning("日志文件无法打开(%s)，仅输出到控制台", exc)

    # 压噪第三方库
    for lib in ("uvicorn.access", "httpx", "uvicorn.error"):
        logging.getLogger(lib).setLevel(logging.WARNING)

    _initialized = True


def get_logger(name: str) -> logging.Logger:
    """业务模块便捷入口。"""
    return logging.getLogger(name)


# --------------------------- 敏感脱敏工具 ---------------------------


def mask_credit_code(code: str | None) -> str:
    """统一社会信用代码脱敏：保留前4后4，中间 **** 填充。"""
    if not code or len(code) < 8:
        return "****"
    return f"{code[:4]}****{code[-4:]}"


def mask_amount(amount: float | int | None) -> str:
    """金额脱敏：四舍五入到万元单位，避免完整数值落日志。"""
    if amount is None or amount == 0:
        return "0"
    return f"{float(amount) / 10000:.1f}万"
