"""AI 预审摘要统一构造函数。

列表页「AI 摘要」（applications.ai_summary，写入来源为预审报告 summary 字段）
与授信助手 get_precheck_summary 工具共用本模块读取同一份落库快照
（rule_results / risk_signals / conflicts / pass_rate / completeness），
避免两处各自拼装字段导致等级、通过率、未通过项数量口径不一致。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

from app.models.enums import AiConclusion  # noqa: E402
from app.schemas.ai_classification import CATEGORY_LABELS, MaterialCategory  # noqa: E402

CONCLUSION_LABELS: dict[str, str] = {
    "pass": "符合",
    "attention": "风险建议关注",
    "forbidden": "建议禁入",
    "manual": "待人工核验",
}

RISK_LEVEL_LABELS = {"high": "高", "medium": "中", "low": "低"}


@dataclass(frozen=True)
class FailedRule:
    """未通过 / 存疑的准入规则条目。"""

    rule_id: str
    rule_name: str
    result: str
    detail: str | None = None


@dataclass(frozen=True)
class PrecheckSummaryView:
    """预审摘要的结构化视图（只读，不重新计算）。"""

    conclusion: str
    summary_text: str
    pass_rate: float | None = None
    pass_count: int = 0
    total_count: int = 0
    hard_fail_count: int = 0
    soft_fail_count: int = 0
    uncertain_count: int = 0
    level: str = ""
    failed_rules: tuple[FailedRule, ...] = field(default_factory=tuple)
    risk_signals: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    conflicts: tuple[dict[str, Any], ...] = field(default_factory=tuple)
    missing: tuple[str, ...] = field(default_factory=tuple)


def build_precheck_summary_view(report: Any) -> PrecheckSummaryView:
    """从已落库的预审报告构造统一摘要视图（兼容 ORM 对象与 dict）。"""
    rules = _get(report, "rule_results") or {}
    if not isinstance(rules, dict):
        rules = {}

    failed: list[FailedRule] = []
    for item in rules.get("rules") or []:
        if not isinstance(item, dict):
            continue
        result = str(item.get("result") or "")
        if result not in ("fail", "uncertain"):
            continue
        failed.append(
            FailedRule(
                rule_id=str(item.get("rule_id") or ""),
                rule_name=str(item.get("rule_name") or ""),
                result=result,
                detail=item.get("detail") or None,
            )
        )

    return PrecheckSummaryView(
        conclusion=_conclusion_value(_get(report, "conclusion")),
        summary_text=str(_get(report, "summary") or ""),
        pass_rate=_float_or_none(_get(report, "pass_rate")),
        pass_count=int(rules.get("pass_count") or 0),
        total_count=int(rules.get("total_count") or 0),
        hard_fail_count=int(rules.get("hard_fail_count") or 0),
        soft_fail_count=int(rules.get("soft_fail_count") or 0),
        uncertain_count=int(rules.get("uncertain_count") or 0),
        level=str(rules.get("level") or ""),
        failed_rules=tuple(failed),
        risk_signals=tuple(
            item for item in (_get(report, "risk_signals") or []) if isinstance(item, dict)
        ),
        conflicts=tuple(
            item for item in (_get(report, "conflicts") or []) if isinstance(item, dict)
        ),
        missing=tuple(missing_category_labels(_get(report, "completeness"))),
    )


def render_precheck_summary_text(
    view: PrecheckSummaryView,
    *,
    app_no: str,
    company_name: str,
) -> str:
    """把摘要视图渲染为面向客户经理的紧凑文本（助手回答沿用该口径）。"""
    lines = [
        f"申请 {app_no}（{company_name}）AI 预审摘要：",
        f"预审结论：{CONCLUSION_LABELS.get(view.conclusion, view.conclusion or '—')}",
    ]
    if view.pass_rate is not None:
        lines.append(f"预估通过率：{view.pass_rate:.1f}%")
    if view.total_count:
        lines.append(
            f"规则匹配：通过 {view.pass_count}/{view.total_count}；"
            f"强规则未通过 {view.hard_fail_count} 项，弱规则未通过 {view.soft_fail_count} 项，"
            f"存疑 {view.uncertain_count} 项；等级 {view.level or '—'}"
        )
    for item in view.failed_rules[:5]:
        label = "不符合" if item.result == "fail" else "存疑"
        suffix = f"：{item.detail}" if item.detail else ""
        lines.append(f"- [{label}] {item.rule_id} {item.rule_name}{suffix}")
    if len(view.failed_rules) > 5:
        lines.append(f"- ……另有 {len(view.failed_rules) - 5} 项，请在预审报告页查看")

    if view.risk_signals:
        lines.append(f"风险信号：共 {len(view.risk_signals)} 条")
        for signal in view.risk_signals[:5]:
            level = RISK_LEVEL_LABELS.get(
                str(signal.get("level")), str(signal.get("level") or "")
            )
            lines.append(f"- [{level}] {signal.get('title', '')}")
        if len(view.risk_signals) > 5:
            lines.append(f"- ……另有 {len(view.risk_signals) - 5} 条")

    if view.conflicts:
        lines.append(f"冲突/低置信项：共 {len(view.conflicts)} 条")
        for conflict in view.conflicts[:3]:
            lines.append(f"- {conflict.get('reason') or conflict.get('type') or '未说明'}")

    if view.missing:
        lines.append(f"缺失材料：{'、'.join(view.missing)}")

    return "\n".join(lines)


def missing_category_labels(completeness: Any) -> list[str]:
    """从完整性快照中提取缺失材料类别中文名。"""
    if not isinstance(completeness, dict):
        return []
    labels: list[str] = []
    for item in completeness.get("missing") or []:
        labels.append(_category_label(item))
    if not labels:
        for category in completeness.get("categories") or []:
            if (
                isinstance(category, dict)
                and category.get("required")
                and not category.get("satisfied")
            ):
                labels.append(
                    str(category.get("label") or _category_label(category.get("category")))
                )
    return labels


# ---------------------------------------------------------------- 内部工具


def _get(obj: Any, name: str) -> Any:
    if isinstance(obj, dict):
        return obj.get(name)
    return getattr(obj, name, None)


def _conclusion_value(conclusion: Any) -> str:
    if isinstance(conclusion, AiConclusion):
        return conclusion.value
    return str(conclusion or "")


def _float_or_none(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _category_label(code: Any) -> str:
    try:
        return CATEGORY_LABELS.get(code, str(code))  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return str(code)


# ---------------------------------------------------------------- AI 解读生成

_INTERPRETATION_MAX_CHARS = 600

_INTERPRETATION_SYSTEM = (
    "你是银行信贷风控助手，负责把 AI 预审快照转述为一段面向客户经理的自然语言解读。"
)

_INTERPRETATION_INSTRUCTION = """请基于以下 AI 预审快照，写一段 200-400 字的中文解读，供客户经理在申请详情页与预审报告页快速阅读理解。

要求：
1. 只转述快照中已有的结论、通过率、未通过/存疑规则、风险信号与缺失材料，禁止重新判定、编造数据或给出快照之外的结论
2. 先说明预审结论与通过率，再按重要程度概述主要问题（未通过项 > 高风险信号 > 存疑项 > 缺失材料），最后给一句办理建议
3. 不得输出完整的统一社会信用代码、身份证号等敏感信息
4. 直接输出解读正文，不要标题、不要列表标记之外的格式

AI 预审快照：
{snapshot}"""


def generate_interpretation(
    report: Any,
    *,
    app_no: str,
    company_name: str,
) -> str:
    """基于预审快照生成 LLM 解读文本（仅转述，不重新判定）。

    任何异常都降级为模板文本（render_precheck_summary_text）并输出 WARNING，
    不向上抛，避免阻断预审主流程。LLM 调用经由 RecordingLLMClient 自动记录 llm_runs。
    """
    view = build_precheck_summary_view(report)
    snapshot = render_precheck_summary_text(view, app_no=app_no, company_name=company_name)

    try:
        from app.llm import get_client

        resp = get_client().chat(
            system=_INTERPRETATION_SYSTEM,
            user=_INTERPRETATION_INSTRUCTION.format(snapshot=snapshot),
            temperature=0.2,
            max_tokens=800,
        )
        text = (resp.content or "").strip()
        if text:
            return text[:_INTERPRETATION_MAX_CHARS]
        logger.warning("AI 解读生成为空，降级为模板文本 app_no=%s", app_no)
    except Exception as exc:  # noqa: BLE001
        logger.warning("AI 解读生成失败，降级为模板文本 app_no=%s: %s", app_no, exc)

    return snapshot
