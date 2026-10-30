"""AI 预审报告 PDF 导出。

使用系统字体（缺失时回退 PyMuPDF 内置中文字体）在服务端生成 PDF，
内容全部取自已落库的 AiReport，保证与生成时的规则版本一致。
"""

import logging
import time
from pathlib import Path
from typing import Any

try:  # PyMuPDF 2.x 以 pymupdf 为主模块名
    import pymupdf as fitz
except ImportError:  # pragma: no cover - 兼容旧版 PyMuPDF
    import fitz

from app.core import config
from app.models.application import Application
from app.models.report import AiReport
from app.schemas.ai_classification import CATEGORY_LABELS, MaterialCategory

logger = logging.getLogger(__name__)

# A4 尺寸与页边距（pt）
PAGE_WIDTH = 595
PAGE_HEIGHT = 842
MARGIN_X = 46
MARGIN_TOP = 52
MARGIN_BOTTOM = 50
CONTENT_WIDTH = PAGE_WIDTH - MARGIN_X * 2

# 优先使用系统字体（中英文等宽正常），缺失时回退到 PyMuPDF 内置中文字体
_SYSTEM_FONT = Path("C:/Windows/Fonts/msyh.ttc")
if _SYSTEM_FONT.is_file():
    FONT_NAME = "report-font"
    FONT_FILE: str | None = str(_SYSTEM_FONT)
    FONT = fitz.Font(fontfile=FONT_FILE)
else:
    FONT_NAME = "china-s"
    FONT_FILE = None
    FONT = fitz.Font(FONT_NAME)

COLOR_TEXT = (0.13, 0.18, 0.25)
COLOR_MUTED = (0.42, 0.47, 0.55)
COLOR_ACCENT = (0.02, 0.45, 0.32)
COLOR_GREEN = (0.02, 0.55, 0.35)
COLOR_AMBER = (0.70, 0.45, 0.02)
COLOR_RED = (0.72, 0.11, 0.11)
COLOR_LINE = (0.85, 0.88, 0.91)
COLOR_HEADER_FILL = (0.96, 0.97, 0.98)

CONCLUSION_LABELS = {
    "pass": "通过",
    "attention": "需关注",
    "forbidden": "建议禁入",
    "manual": "待人工核验",
}
CONCLUSION_TONES = {
    "pass": (COLOR_GREEN, (0.94, 0.99, 0.96)),
    "attention": (COLOR_AMBER, (1.0, 0.98, 0.93)),
    "manual": (COLOR_AMBER, (1.0, 0.98, 0.93)),
    "forbidden": (COLOR_RED, (1.0, 0.96, 0.96)),
}
RULE_STATUS = {
    "pass": ("符合", COLOR_GREEN),
    "fail": ("不符合", COLOR_RED),
    "uncertain": ("存疑", COLOR_AMBER),
}
CONSISTENCY_STATUS = {
    "pass": ("一致", COLOR_GREEN),
    "fail": ("不一致", COLOR_RED),
    "uncertain": ("无法判定", COLOR_AMBER),
}
SEVERITY_LABELS = {"high": "高", "medium": "中", "low": "低", "none": "—"}
RISK_LEVELS = {"high": ("高", COLOR_RED), "medium": ("中", COLOR_AMBER), "low": ("低", COLOR_GREEN)}
CONFLICT_TYPES = {
    "low_confidence": "分类低置信",
    "rule_conflict": "规则证据不足",
    "data_inconsistent": "数据不一致",
}


def _wrap(text: Any, size: float, max_width: float) -> list[str]:
    """按字符宽度折行，兼容中英文混排。"""
    content = "" if text is None else str(text)
    lines: list[str] = []
    for raw in content.split("\n"):
        current = ""
        for char in raw:
            if FONT.text_length(current + char, fontsize=size) <= max_width:
                current += char
            else:
                lines.append(current)
                current = char
        lines.append(current)
    return lines or [""]


def _text(
    page: fitz.Page,
    x: float,
    y: float,
    content: Any,
    size: float = 9.5,
    color: tuple[float, float, float] = COLOR_TEXT,
) -> None:
    page.insert_text(
        (x, y),
        str(content),
        fontname=FONT_NAME,
        fontfile=FONT_FILE,
        fontsize=size,
        color=color,
    )


def _clip(content: Any, size: float, max_width: float) -> str:
    """超宽文本截断并补省略号，避免跨列重叠。"""
    text = "" if content is None else str(content)
    if FONT.text_length(text, fontsize=size) <= max_width:
        return text
    while text and FONT.text_length(text + "…", fontsize=size) > max_width:
        text = text[:-1]
    return text + "…"


def _num(value: Any) -> str:
    try:
        return f"{float(value):g}"
    except (TypeError, ValueError):
        return _fmt(value)


def _fmt(value: Any, suffix: str = "") -> str:
    if value is None or value == "":
        return "—"
    return f"{value}{suffix}"


def _datetime(value: Any) -> str:
    if not value:
        return "—"
    return str(value).replace("T", " ")[:16]


def _category_label(raw: Any) -> str:
    try:
        return CATEGORY_LABELS[MaterialCategory(str(raw))]
    except (ValueError, KeyError):
        return "申请信息" if raw == "application" else str(raw)


class _PdfWriter:
    """按纵向游标顺序排版，自动分页并重复表头。"""

    def __init__(self, app_no: str):
        self.doc = fitz.open()
        self.app_no = app_no
        self.page: fitz.Page
        self.y = 0.0
        self._new_page()

    def _new_page(self) -> None:
        self.page = self.doc.new_page(width=PAGE_WIDTH, height=PAGE_HEIGHT)
        self.y = MARGIN_TOP
        # 页眉
        _text(self.page, MARGIN_X, 30, "AI 预审报告", size=8, color=COLOR_MUTED)
        header = f"申请编号 {self.app_no}"
        header_width = FONT.text_length(header, fontsize=8)
        _text(
            self.page,
            PAGE_WIDTH - MARGIN_X - header_width,
            30,
            header,
            size=8,
            color=COLOR_MUTED,
        )
        self.page.draw_line(
            (MARGIN_X, 38), (PAGE_WIDTH - MARGIN_X, 38), color=COLOR_LINE, width=0.6
        )
        # 页脚
        footer_y = PAGE_HEIGHT - 32
        self.page.draw_line(
            (MARGIN_X, footer_y), (PAGE_WIDTH - MARGIN_X, footer_y), color=COLOR_LINE, width=0.6
        )
        footer = f"第 {len(self.doc)} 页"
        footer_width = FONT.text_length(footer, fontsize=8)
        _text(
            self.page,
            (PAGE_WIDTH - footer_width) / 2,
            footer_y + 14,
            footer,
            size=8,
            color=COLOR_MUTED,
        )

    def _ensure(self, height: float) -> None:
        if self.y + height > PAGE_HEIGHT - MARGIN_BOTTOM:
            self._new_page()

    def space(self, height: float) -> None:
        self.y += height

    def heading(self, title: str) -> None:
        size = 13
        self._ensure(size + 26)
        self.y += 16
        _text(self.page, MARGIN_X, self.y + size, title, size=size, color=COLOR_ACCENT)
        self.y += size + 6
        self.page.draw_line(
            (MARGIN_X, self.y), (PAGE_WIDTH - MARGIN_X, self.y), color=COLOR_LINE, width=0.6
        )
        self.y += 8

    def paragraph(
        self,
        text: Any,
        size: float = 9.5,
        color: tuple[float, float, float] = COLOR_TEXT,
        gap: float = 4,
        indent: float = 0,
    ) -> None:
        line_height = size * 1.65
        for line in _wrap(text, size, CONTENT_WIDTH - indent):
            self._ensure(line_height)
            _text(self.page, MARGIN_X + indent, self.y + size, line, size=size, color=color)
            self.y += line_height
        self.y += gap

    def meta_row(self, left: tuple[str, Any], right: tuple[str, Any]) -> None:
        """一行两组「标签值」，左右各占半栏。"""
        self._ensure(17)
        half = CONTENT_WIDTH / 2
        for x, (label, value) in ((MARGIN_X, left), (MARGIN_X + half, right)):
            _text(self.page, x, self.y + 10, label, size=8.5, color=COLOR_MUTED)
            offset = FONT.text_length(label, fontsize=8.5) + 4
            _text(
                self.page,
                x + offset,
                self.y + 10,
                _clip(_fmt(value), 9.5, half - offset - 8),
                size=9.5,
                color=COLOR_TEXT,
            )
        self.y += 17

    def table_header(self, headers: list[str], widths: list[float]) -> None:
        height = 22
        self._ensure(height)
        top = self.y
        self.page.draw_rect(
            fitz.Rect(MARGIN_X, top, MARGIN_X + sum(widths), top + height),
            color=None,
            fill=COLOR_HEADER_FILL,
        )
        for idx, header in enumerate(headers):
            x = MARGIN_X + sum(widths[:idx])
            _text(self.page, x + 4, top + 14.5, header, size=8.5, color=COLOR_MUTED)
        self.page.draw_line(
            (MARGIN_X, top + height),
            (MARGIN_X + sum(widths), top + height),
            color=COLOR_LINE,
            width=0.6,
        )
        self.y = top + height

    def table(
        self,
        headers: list[str],
        widths: list[float],
        rows: list[list[tuple[Any, tuple[float, float, float]]]],
    ) -> None:
        self.table_header(headers, widths)
        size = 8.5
        line_height = 12
        for cells in rows:
            wrapped = [_wrap(text, size, width - 8) for (text, _), width in zip(cells, widths)]
            height = max(len(lines) for lines in wrapped) * line_height + 8
            if self.y + height > PAGE_HEIGHT - MARGIN_BOTTOM:
                self._new_page()
                self.table_header(headers, widths)
            top = self.y
            for idx, (lines, (_, color)) in enumerate(zip(wrapped, cells)):
                x = MARGIN_X + sum(widths[:idx])
                baseline = top + (height - len(lines) * line_height) / 2 + size + 2
                for line in lines:
                    _text(self.page, x + 4, baseline, line, size=size, color=color)
                    baseline += line_height
            self.page.draw_line(
                (MARGIN_X, top + height),
                (MARGIN_X + sum(widths), top + height),
                color=COLOR_LINE,
                width=0.5,
            )
            self.y = top + height
        self.y += 4


def _draw_title(writer: _PdfWriter, app: Application, report: AiReport) -> None:
    _text(writer.page, MARGIN_X, writer.y + 24, "AI 预审报告", size=22, color=COLOR_TEXT)
    writer.y += 34
    writer.paragraph(f"{app.company_name} · {app.app_no}", size=10, color=COLOR_MUTED, gap=2)

    conclusion = getattr(report.conclusion, "value", report.conclusion)
    color, fill = CONCLUSION_TONES.get(conclusion, (COLOR_AMBER, (1.0, 0.98, 0.93)))
    summary_lines = _wrap(report.summary or "—", 9.5, CONTENT_WIDTH - 30)
    box_height = 34 + len(summary_lines) * 15 + 8
    writer._ensure(box_height)
    top = writer.y
    writer.page.draw_rect(
        fitz.Rect(MARGIN_X, top, MARGIN_X + CONTENT_WIDTH, top + box_height),
        color=None,
        fill=fill,
    )
    writer.page.draw_rect(
        fitz.Rect(MARGIN_X, top, MARGIN_X + 4, top + box_height), color=None, fill=color
    )
    _text(
        writer.page,
        MARGIN_X + 14,
        top + 20,
        f"准入初判：{CONCLUSION_LABELS.get(conclusion, conclusion)}",
        size=13,
        color=color,
    )
    baseline = top + 38
    for line in summary_lines:
        _text(writer.page, MARGIN_X + 14, baseline, line, size=9.5, color=COLOR_TEXT)
        baseline += 15
    writer.y = top + box_height + 10

    rule_matching = report.rule_results or {}
    stats = [
        (
            f"{_num(rule_matching.get('score', 0))} 分 · {rule_matching.get('level', '—')}",
            "准入评分 / 等级",
        ),
        (f"{float(report.pass_rate or 0):.0f}%", "预估通过率"),
        (
            f"{rule_matching.get('pass_count', 0)}/{rule_matching.get('total_count', 0)}",
            "规则通过条数",
        ),
    ]
    box_gap = 10
    box_width = (CONTENT_WIDTH - box_gap * 2) / 3
    box_height = 52
    writer._ensure(box_height)
    top = writer.y
    for idx, (value, label) in enumerate(stats):
        x = MARGIN_X + idx * (box_width + box_gap)
        writer.page.draw_rect(
            fitz.Rect(x, top, x + box_width, top + box_height),
            color=COLOR_LINE,
            fill=(0.98, 0.99, 1.0),
            width=0.5,
        )
        _text(writer.page, x + 12, top + 24, value, size=16, color=COLOR_TEXT)
        _text(writer.page, x + 12, top + 42, label, size=8.5, color=COLOR_MUTED)
    writer.y = top + box_height + 6

    writer.meta_row(
        ("贷款产品：", app.product),
        ("申请金额：", f"{float(app.amount):.2f} 万元"),
    )
    writer.meta_row(
        ("客户经理：", app.manager_name),
        ("提交时间：", _datetime(app.created_at)),
    )
    writer.meta_row(
        ("统一社会信用代码：", app.credit_code),
        ("报告生成时间：", _datetime(report.created_at)),
    )
    writer.meta_row(
        ("报告版本：", report.version),
        ("规则版本：", report.rule_version),
    )


def _draw_completeness(writer: _PdfWriter, report: AiReport) -> None:
    writer.heading("一、材料完整性结论")
    completeness = report.completeness or {}
    required = completeness.get("required") or []
    categories = completeness.get("categories") or []
    satisfied = sum(
        1 for item in categories if item.get("required") and item.get("satisfied")
    )
    coverage = float(completeness.get("coverage_rate") or 0) * 100
    writer.paragraph(
        f"必备材料齐全度：{satisfied}/{len(required) or len(categories) or 0} 类　　"
        f"材料总份数：{completeness.get('total_materials', 0)} 份　　覆盖率：{coverage:.0f}%",
    )
    issues = completeness.get("issues") or []
    if issues:
        for issue in issues:
            writer.paragraph(f"• {issue.get('message', '')}", color=COLOR_RED, indent=8)
    else:
        writer.paragraph("未发现材料完整性问题。", color=COLOR_GREEN)

    if categories:
        rows = []
        for item in categories:
            required_flag = "是" if item.get("required") else "否"
            if item.get("required"):
                status = ("齐全", COLOR_GREEN) if item.get("satisfied") else ("不足", COLOR_RED)
            else:
                status = ("—", COLOR_MUTED)
            rows.append(
                [
                    (item.get("label", item.get("category", "")), COLOR_TEXT),
                    (required_flag, COLOR_MUTED),
                    (f"{item.get('count', 0)} 份", COLOR_TEXT),
                    status,
                    (item.get("requirement") or "—", COLOR_MUTED),
                ]
            )
        writer.table(
            ["材料类别", "必备", "份数", "状态", "产品要求"],
            [96, 40, 48, 48, CONTENT_WIDTH - 232],
            rows,
        )


def _draw_consistency(writer: _PdfWriter, report: AiReport) -> None:
    writer.heading("二、材料一致性校验")
    consistency = report.consistency or {}
    checks = consistency.get("checks") or []
    fail_count = sum(1 for item in checks if item.get("status") == "fail")
    uncertain_count = sum(1 for item in checks if item.get("status") == "uncertain")
    writer.paragraph(
        f"共 {len(checks)} 项校验：不一致 {fail_count} 项，无法判定 {uncertain_count} 项。"
    )
    if not checks:
        writer.paragraph("未执行一致性校验。", color=COLOR_MUTED)
        return

    rows = []
    for item in checks:
        status = CONSISTENCY_STATUS.get(item.get("status"), (item.get("status", ""), COLOR_TEXT))
        severity = SEVERITY_LABELS.get(item.get("severity"), item.get("severity") or "—")
        values = "；".join(
            f"{_category_label(value.get('source'))}：{value.get('value', '')}"
            for value in (item.get("values") or [])
        ) or "—"
        rows.append(
            [
                (item.get("check_item", ""), COLOR_TEXT),
                (status[0], status[1]),
                (severity, COLOR_RED if severity == "高" else COLOR_TEXT),
                (values, COLOR_TEXT),
                (item.get("suggestion") or "—", COLOR_MUTED),
            ]
        )
    writer.table(
        ["校验项", "结论", "严重度", "各来源取值", "处理建议"],
        [92, 46, 38, 216, CONTENT_WIDTH - 392],
        rows,
    )


def _draw_rules(writer: _PdfWriter, report: AiReport) -> None:
    writer.heading("三、准入规则匹配（逐条依据）")
    matching = report.rule_results or {}
    rules = matching.get("rules") or []
    writer.paragraph(
        f"规则版本：{matching.get('rule_version') or report.rule_version or '—'}　　"
        f"评分：{_num(matching.get('score', 0))} 分　　"
        f"等级：{matching.get('level', '—')}（{matching.get('level_label') or '—'}）　　"
        f"通过：{matching.get('pass_count', 0)}/{matching.get('total_count', 0)} 条　　"
        f"强规则未通过：{matching.get('hard_fail_count', 0)} 条　　"
        f"弱规则未通过：{matching.get('soft_fail_count', 0)} 条　　"
        f"存疑：{matching.get('uncertain_count', 0)} 条"
    )
    if matching.get("level_note"):
        writer.paragraph(f"等级说明：{matching['level_note']}", size=9, color=COLOR_MUTED)
    if not rules:
        writer.paragraph("暂无准入规则匹配结果。", color=COLOR_MUTED)
        return

    rows = []
    for rule in rules:
        status = RULE_STATUS.get(rule.get("result"), (str(rule.get("result", "")), COLOR_TEXT))
        kind = "强规则" if rule.get("kind") == "hard" else "弱规则"
        rows.append(
            [
                (f"{rule.get('rule_name', '')}\n{rule.get('rule_id', '')} · {kind}", COLOR_TEXT),
                (rule.get("actual") or "—", COLOR_TEXT),
                (rule.get("expected") or "—", COLOR_MUTED),
                (status[0], status[1]),
                (rule.get("detail") or "—", COLOR_MUTED),
            ]
        )
    writer.table(
        ["规则项", "客户值", "规则要求", "结论", "依据条款"],
        [118, 86, 96, 44, CONTENT_WIDTH - 344],
        rows,
    )


def _draw_risks(writer: _PdfWriter, report: AiReport) -> None:
    writer.heading("四、风险信号汇总")
    signals = report.risk_signals or []
    if not signals:
        writer.paragraph("暂无风险信号。", color=COLOR_MUTED)
        return
    rows = []
    for signal in signals:
        level = RISK_LEVELS.get(signal.get("level"), (str(signal.get("level", "")), COLOR_TEXT))
        evidence = signal.get("evidence") or {}
        source = evidence.get("source")
        detail = evidence.get("detail") or "—"
        rows.append(
            [
                (signal.get("category") or "—", COLOR_TEXT),
                (signal.get("title") or "—", COLOR_TEXT),
                (level[0], level[1]),
                (signal.get("suggestion") or "—", COLOR_MUTED),
                (
                    f"{_category_label(source)}：{detail}" if source else detail,
                    COLOR_MUTED,
                ),
            ]
        )
    writer.table(
        ["维度", "信号", "优先级", "处理建议", "证据引用"],
        [58, 98, 40, 128, CONTENT_WIDTH - 324],
        rows,
    )


def _draw_conflicts(writer: _PdfWriter, report: AiReport) -> None:
    writer.heading("五、低置信 / 规则冲突项（强制人工核验）")
    conflicts = report.conflicts or []
    if not conflicts:
        writer.paragraph("暂无低置信或规则冲突项。", color=COLOR_GREEN)
        return
    for item in conflicts:
        title = CONFLICT_TYPES.get(item.get("type"), item.get("type") or "冲突项")
        rule_ids = item.get("rules") or []
        if rule_ids:
            title = f"{title} · {'/'.join(rule_ids)}"
        writer.paragraph(title, size=9.5, color=COLOR_AMBER, gap=1)
        writer.paragraph(f"原因：{item.get('reason') or '—'}", size=9, indent=8, gap=1)
        if item.get("source"):
            writer.paragraph(
                f"来源：{_category_label(item['source'])}"
                f"{' · ' + item['field'] if item.get('field') else ''}",
                size=9,
                indent=8,
                gap=1,
            )
        if item.get("value"):
            writer.paragraph(f"涉及取值：{item['value']}", size=9, indent=8, gap=1)
        writer.paragraph("处置建议：转人工核验", size=9, indent=8, color=COLOR_MUTED)


def build_report_pdf(app: Application, report: AiReport) -> bytes:
    """生成预审报告 PDF 字节流。"""
    writer = _PdfWriter(app.app_no)
    _draw_title(writer, app, report)
    _draw_completeness(writer, report)
    _draw_consistency(writer, report)
    _draw_rules(writer, report)
    _draw_risks(writer, report)
    _draw_conflicts(writer, report)

    writer._ensure(30)
    writer.paragraph(
        f"本报告由系统依据规则版本 {report.rule_version or '—'} 自动生成，"
        "判定结果仅供参考，最终授信结论以人工复核与风控决策为准。",
        size=8.5,
        color=COLOR_MUTED,
    )
    # 只嵌入实际用到的字形，避免把完整中文字体打进 PDF
    writer.doc.subset_fonts()
    return writer.doc.tobytes()


def report_pdf_path(app_no: str) -> Path:
    """报告 PDF 的落盘位置（随申请一起删除）。"""
    return Path(config.UPLOAD_DIR) / app_no / "ai_report.pdf"


def get_report_pdf(app: Application, report: AiReport) -> bytes:
    """优先复用已保存的 PDF；报告更新后（材料/信息变更）重新生成并覆盖。"""
    path = report_pdf_path(app.app_no)
    updated_at = report.updated_at
    if path.is_file() and updated_at and path.stat().st_mtime >= updated_at.timestamp() - 1:
        logger.info("PDF 缓存命中, app_no=%s, 缓存文件=%s", app.app_no, path.name)
        return path.read_bytes()

    t0 = time.perf_counter()
    content = build_report_pdf(app, report)
    elapsed = time.perf_counter() - t0
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)
    size_kb = len(content) / 1024
    logger.info(
        "PDF 生成, app_no=%s, 耗时=%.2fs, 大小=%.1fKB",
        app.app_no,
        elapsed,
        size_kb,
    )
    return content
