"""AI 材料分析服务。"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.enums import AiConclusion, ApplicationStatus
from app.models.material import Material
from app.models.report import AiReport
from app.schemas.ai_analysis import (
    AiReportSummary,
    CategoryCompleteness,
    CompletenessIssue,
    CompletenessResult,
    ConflictItem,
    ConflictSummary,
    ConflictType,
    ConsistencyCheck,
    ConsistencyResult,
    ConsistencySeverity,
    ConsistencyStatus,
    ConsistencyValue,
    DEFAULT_REQUIRED_CATEGORIES,
    RiskEvidence,
    RiskLevel,
    RiskSignal,
    RiskSummary,
    RuleEvidence,
    RuleMatchItem,
    RuleMatchResult,
    RuleMatchStatus,
)
from app.schemas.ai_classification import (
    CATEGORY_LABELS,
    LOW_CONFIDENCE_THRESHOLD,
    MaterialCategory,
    MaterialClassifyInput,
    MimeType,
)
from app.services.classifier import load_text
from app.services.rule_config import extra_required_categories, load_rule_config

# ---------------------------------------------------------------- 完整性规则

# 五大公共必交材料：所有产品均必须提供（产品专属材料从规则文件读取）
CORE_REQUIRED_CATEGORIES: list[MaterialCategory] = list(DEFAULT_REQUIRED_CATEGORIES)

# 银行流水需覆盖超过该月数
MIN_BANK_STATEMENT_MONTHS = 6
# 财务报表需齐全的三表
FINANCIAL_TABLE_KEYWORDS = ("资产负债表", "利润表", "现金流量表")

SUFFIX_MIME = {
    ".pdf": MimeType.PDF,
    ".jpg": MimeType.JPEG,
    ".jpeg": MimeType.JPEG,
    ".png": MimeType.PNG,
}

# 对账单统计期间，如「2025年1月1日至2025年1月31日」（兼容 OCR 空格分行）
_PERIOD_RE = re.compile(
    r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*\d{1,2}\s*日\s*至\s*"
    r"(\d{4})\s*年\s*(\d{1,2})\s*月"
)
# 交易日期，如「2025-01-02」
_DATE_RE = re.compile(r"(20\d{2})-(\d{1,2})-\d{1,2}")


def _category_of(material: Material) -> MaterialCategory:
    """材料类别编码转枚举，无法识别时按其他处理。"""
    try:
        return MaterialCategory(material.category)
    except ValueError:
        return MaterialCategory.OTHER


def _read_text(material: Material) -> str:
    """读取材料 OCR 文本：优先用落库文本，缺失时才重新识别。"""
    if material.ocr_text:
        return material.ocr_text
    suffix = Path(material.file_name).suffix.lower()
    mime_type = SUFFIX_MIME.get(suffix)
    if mime_type is None or not material.file_url:
        return ""
    return load_text(
        MaterialClassifyInput(
            file_name=material.file_name,
            mime_type=mime_type,
            file_path=material.file_url,
        )
    )


def _compact(text: str) -> str:
    """去掉所有空白字符，避免 OCR 分字导致关键词漏判。"""
    return re.sub(r"\s+", "", text)


def _statement_months(texts: Sequence[str]) -> set[tuple[int, int]]:
    """从流水文本中提取交易期间覆盖的年月集合。"""
    months: set[tuple[int, int]] = set()
    for text in texts:
        has_period = False
        for match in _PERIOD_RE.finditer(text):
            has_period = True
            start_year, start_month, end_year, end_month = (
                int(group) for group in match.groups()
            )
            if (end_year, end_month) < (start_year, start_month):
                continue
            year, month = start_year, start_month
            while (year, month) <= (end_year, end_month):
                months.add((year, month))
                month += 1
                if month > 12:
                    year, month = year + 1, 1
        if not has_period:
            for match in _DATE_RE.finditer(text):
                months.add((int(match.group(1)), int(match.group(2))))
    return months


def analyze_completeness(
    materials: Sequence[Material], product: str | None = None
) -> CompletenessResult:
    """2.1 材料完整性判断。

    判定规则：
    1. 五大公共必交材料每类至少 1 份（营业执照、银行流水、财务报表、
       纳税申报表、征信授权书）；
    2. 产品专属必交材料从 rules/rule_<产品>.yaml 的 required_categories
       读取，缺失同样提示补件；
    3. 内容可读：OCR 文本为空视为内容不完整，需重传；
    4. 特殊要求：银行流水需覆盖超过 6 个月，财务报表需资产负债表、
       利润表、现金流量表三表齐全。
    """
    counts = {category: 0 for category in MaterialCategory}
    texts: dict[int, str] = {}
    for material in materials:
        counts[_category_of(material)] += 1
        texts[material.id] = _read_text(material)

    # 公共必交材料 + 规则文件中的产品专属必交材料
    required = list(CORE_REQUIRED_CATEGORIES)
    min_counts = {category: 1 for category in required}
    extra_desc: dict[MaterialCategory, str] = {}
    for category, min_count, desc in extra_required_categories(product or ""):
        if category not in required:
            required.append(category)
        min_counts[category] = max(min_counts.get(category, 1), min_count)
        if desc:
            extra_desc[category] = desc

    missing = [category for category in required if counts[category] < min_counts[category]]
    core_missing = [category for category in missing if category in CORE_REQUIRED_CATEGORIES]
    extra_missing = [category for category in missing if category not in CORE_REQUIRED_CATEGORIES]

    issues: list[CompletenessIssue] = []

    if core_missing:
        issues.append(
            CompletenessIssue(
                type="missing",
                message="缺少必备材料：" + "、".join(CATEGORY_LABELS[c] for c in core_missing),
            )
        )

    if extra_missing:
        parts: list[str] = []
        for category in extra_missing:
            label = CATEGORY_LABELS[category]
            desc = extra_desc.get(category)
            need = min_counts[category]
            if counts[category] == 0:
                parts.append(f"{label}（{desc}）" if desc else label)
            else:
                parts.append(f"{label}需至少 {need} 份，当前 {counts[category]} 份")
        issues.append(
            CompletenessIssue(
                type="missing",
                message="缺少产品专属必备材料：" + "、".join(parts),
            )
        )

    unreadable = [
        material.file_name for material in materials if not texts[material.id].strip()
    ]
    if unreadable:
        issues.append(
            CompletenessIssue(
                type="unreadable",
                message="内容不完整，需重传：" + "、".join(unreadable),
            )
        )

    # 特殊要求一：银行流水需覆盖超过 6 个月
    bank_texts = [
        texts[material.id]
        for material in materials
        if _category_of(material) == MaterialCategory.BANK_STATEMENT
    ]
    readable_bank_texts = [text for text in bank_texts if text.strip()]
    if readable_bank_texts:
        months = _statement_months(readable_bank_texts)
        if not months:
            issues.append(
                CompletenessIssue(
                    type="period", message="银行流水交易期间无法识别，需人工核验"
                )
            )
        elif len(months) <= MIN_BANK_STATEMENT_MONTHS:
            issues.append(
                CompletenessIssue(
                    type="period",
                    message=(
                        f"银行流水仅覆盖 {len(months)} 个月，"
                        f"需覆盖超过 {MIN_BANK_STATEMENT_MONTHS} 个月"
                    ),
                )
            )

    # 特殊要求二：财务报表需三表齐全
    if counts[MaterialCategory.FINANCIAL_REPORT]:
        report_texts = [
            _compact(texts[material.id])
            for material in materials
            if _category_of(material) == MaterialCategory.FINANCIAL_REPORT
        ]
        missing_tables = [
            name
            for name in FINANCIAL_TABLE_KEYWORDS
            if not any(name in text for text in report_texts)
        ]
        if missing_tables:
            issues.append(
                CompletenessIssue(
                    type="tables",
                    message="财务报表缺少：" + "、".join(missing_tables),
                )
            )

    satisfied_required = sum(
        1 for category in required if counts[category] >= min_counts[category]
    )
    return CompletenessResult(
        is_complete=not issues,
        required=required,
        missing=missing,
        coverage_rate=satisfied_required / len(required),
        total_materials=len(materials),
        categories=[
            CategoryCompleteness(
                category=category,
                label=CATEGORY_LABELS[category],
                required=category in required,
                count=counts[category],
                satisfied=counts[category] >= min_counts.get(category, 1),
                requirement=extra_desc.get(category),
            )
            for category in MaterialCategory
        ],
        issues=issues,
    )


def generate_report(
    db: Session, app: Application, materials: Sequence[Material]
) -> AiReport:
    """材料分类完成后自动执行 AI 预审：生成或更新该申请的预审报告。

    预审包含材料完整性判断、一致性校验（P1）与按下发 YAML 执行的
    准入规则逐条匹配，结论按规则文件的 conclusion_logic 推导。
    """
    # 兜底 OCR 回写：补齐缺失的识别文本并随本次事务落库，
    # 避免历史材料因 ocr_text 为空在每次预审时重复识别
    for material in materials:
        if not material.ocr_text:
            text = _read_text(material)
            if text.strip():
                material.ocr_text = text

    completeness = analyze_completeness(materials, app.product)
    consistency = check_consistency(app, materials)

    # 绑定本次预审使用的规则版本，并快照规则文件内容：
    # 后续修改 YAML 不影响历史报告的判定依据
    rule_config = load_rule_config(app.product)
    rule_matching = match_rules(app, materials, consistency, rule_config)
    risk_summary = summarize_risk_signals(completeness, consistency, rule_matching)
    conflict_summary = collect_conflicts(materials, consistency, rule_matching)
    summary = build_summary(completeness, consistency, rule_matching, rule_config)

    report = db.scalar(
        select(AiReport).where(AiReport.app_id == app.id).order_by(AiReport.id.desc())
    )
    if report is None:
        report = AiReport(app_id=app.id, version="v1")
        db.add(report)

    report.conclusion = summary.conclusion
    report.summary = summary.summary
    report.pass_rate = Decimal(str(round(summary.pass_rate, 2)))
    report.completeness = completeness.model_dump(mode="json")
    report.consistency = consistency.model_dump(mode="json")
    report.rule_results = rule_matching.model_dump(mode="json")
    report.risk_signals = [item.model_dump(mode="json") for item in risk_summary.risk_signals]
    report.conflicts = [item.model_dump(mode="json") for item in conflict_summary.conflicts]

    report.rule_version = (
        str(rule_config["version"]) if rule_config and rule_config.get("version") else None
    )
    report.rule_snapshot = jsonable_encoder(rule_config) if rule_config else None

    # 同步申请表 AI 摘要，供申请列表展示最新预审结论
    app.ai_summary = summary.summary

    # 预审完成后推进申请进度：材料不齐 → 待补件；齐全 → 待人工核验
    # 风控退回的补件（supplement_source=risk）补齐后直接回流风控复核队列
    # 已进入风控复核及之后的状态不回退
    if (
        not completeness.is_complete
        and app.status
        in {ApplicationStatus.CHECK, ApplicationStatus.SUPPLEMENT, ApplicationStatus.MANUAL}
    ):
        app.status = ApplicationStatus.SUPPLEMENT
    elif completeness.is_complete and app.status in {
        ApplicationStatus.CHECK,
        ApplicationStatus.SUPPLEMENT,
    }:
        back_to_risk = (
            app.status == ApplicationStatus.SUPPLEMENT
            and app.supplement_source == "risk"
        )
        app.status = ApplicationStatus.RISK if back_to_risk else ApplicationStatus.MANUAL
        app.supplement_source = None

    db.commit()
    db.refresh(report)
    return report


# ---------------------------------------------------------------- 一致性规则

# 征信授权书签署后超过该月数视为失效
AUTH_SIGN_VALID_MONTHS = 6
AUTH_SIGN_VALID_DAYS = AUTH_SIGN_VALID_MONTHS * 31
# 金额勾稽容差（元）
AMOUNT_TOLERANCE = 1.0

# 金额：带千分位或小数，天然排除「行次」等小整数
_AMOUNT_RE = re.compile(r"\d{1,3}(?:,\d{3})+(?:\.\d{1,2})?|\d+\.\d{1,2}")
# 中文日期，如「2026 年10 月24 日」
_CN_DATE_RE = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
# 期间结束日，如「至2025年12月31日」
_PERIOD_END_RE = re.compile(r"至\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
_CREDIT_CODE_RE = re.compile(r"[0-9A-Z]{18}")


def _to_amount(token: str) -> float:
    return float(token.replace(",", ""))


def _amounts_after(
    text: str, label: str, limit: int = 3, forbid_prefix: str = "动"
) -> list[float]:
    """取标签之后窗口内的金额，自动过滤行号并跳过「流动负债合计」等近似标签。"""
    index = text.find(label)
    while index >= 0 and index > 0 and text[index - 1] in forbid_prefix:
        index = text.find(label, index + 1)
    if index < 0:
        return []
    window = text[index + len(label) : index + len(label) + 200]
    values: list[float] = []
    for match in _AMOUNT_RE.finditer(window):
        values.append(_to_amount(match.group()))
        if len(values) >= limit:
            break
    return values


def _amount_after_label(text: str, label: str) -> float | None:
    """读取「标签：金额」形式的单个金额。"""
    match = re.search(label + r"[：:]\s*([\d,]+(?:\.\d+)?)", text)
    return _to_amount(match.group(1)) if match else None


def _first_group(pattern: str, text: str) -> str | None:
    match = re.search(pattern, text)
    return match.group(1).strip() if match else None


def _date_after(text: str, label: str) -> date | None:
    """读取标签之后的中文日期。"""
    index = text.find(label)
    if index < 0:
        return None
    match = _CN_DATE_RE.search(text, index + len(label), index + len(label) + 80)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _period_end(text: str) -> date | None:
    match = _PERIOD_END_RE.search(text)
    if not match:
        return None
    try:
        return date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    except ValueError:
        return None


def _norm_company(name: str | None) -> str:
    """企业名称归一化：去空白与 OCR 噪声标点，保留括号内容。"""
    return re.sub(r"[\s　、，,。；;]", "", name or "")


def _credit_code_after(text: str, label: str) -> str | None:
    """读取标签之后出现的 18 位统一社会信用代码（允许中间夹杂 OCR 噪声行）。"""
    index = text.find(label)
    if index < 0:
        return None
    match = _CREDIT_CODE_RE.search(text, index + len(label), index + len(label) + 150)
    return match.group() if match else None


def _extract_license(text: str) -> dict[str, str | None]:
    return {
        "name": _first_group(r"名\s*称\s*([^\n]{2,60}?公司)", text),
        "credit_code": _credit_code_after(text, "统一社会信用代码"),
        "legal_person": _first_group(r"法定代表人[：:\s]*([\u4e00-\u9fa5·]{2,12})", text),
    }


def _extract_bank(text: str) -> dict[str, object]:
    totals = _amounts_after(text, "本月合计", 3)
    return {
        "account_name": _first_group(r"户名[：:]\s*([^\s]+)", text),
        "account_no": _first_group(r"账号[：:]\s*([0-9]{8,25})", text),
        "period": _PERIOD_RE.search(text),
        "opening": _amount_after_label(text, "期初余额"),
        "closing": _amount_after_label(text, "期末余额"),
        "income": totals[0] if totals else None,
        "expense": totals[1] if len(totals) > 1 else None,
    }


def _extract_financial(text: str) -> dict[str, object]:
    revenue = _amounts_after(text, "营业收入", 1)
    profit = _amounts_after(text, "利润总额", 1)
    assets = _amounts_after(text, "资产总计", 2)
    liabilities = _amounts_after(text, "负债合计", 2)
    equity = _amounts_after(text, "所有者权益合计", 2)
    first_line = next((line.strip() for line in text.splitlines() if line.strip()), "")
    return {
        "name": first_line or None,
        "year": _PERIOD_RE.search(text),
        "has_balance_sheet": "资产负债表" in _compact(text),
        "revenue": revenue[0] if revenue else None,
        "profit": profit[0] if profit else None,
        "assets": assets[-1] if assets else None,
        "liabilities": liabilities[-1] if liabilities else None,
        "equity": equity[-1] if equity else None,
        "period_end": _period_end(text),
    }


def _extract_tax(text: str) -> dict[str, object]:
    revenue = _amounts_after(text, "营业收入", 1)
    profit = _amounts_after(text, "利润总额", 1)
    return {
        "name": _first_group(r"纳税人名称[：:\s]*([^\n]{2,80})", text),
        "taxpayer_id": _first_group(r"纳税人识别号[：:\s]*([0-9A-Z]{15,20})", text),
        "year": _PERIOD_RE.search(text),
        "revenue": revenue[0] if revenue else None,
        "profit": profit[0] if profit else None,
        "period_end": _period_end(text),
    }


def _extract_credit_auth(text: str) -> dict[str, object]:
    return {
        "name": _first_group(r"公司全称[：:]\s*([^\n]+)", text),
        "credit_code": _first_group(r"统一社会信用代码[：:]\s*([0-9A-Z]{18})", text),
        "legal_person": _first_group(r"法定代表人[：:\s]*([\u4e00-\u9fa5·]{2,12})", text),
        "signed_at": _date_after(text, "签署日期"),
        "valid_until": _date_after(text, "有效期自签署之日起至"),
    }


def _build_check(
    check_item: str,
    field: str,
    values: list[ConsistencyValue],
    status: ConsistencyStatus,
    severity: ConsistencySeverity,
    suggestion: str | None = None,
) -> ConsistencyCheck:
    return ConsistencyCheck(
        check_item=check_item,
        field=field,
        values=values,
        status=status,
        severity=severity,
        suggestion=suggestion,
    )


def _uncertain(
    check_item: str,
    field: str,
    values: list[ConsistencyValue],
    severity: ConsistencySeverity,
) -> ConsistencyCheck:
    return _build_check(
        check_item,
        field,
        values,
        ConsistencyStatus.UNCERTAIN,
        severity,
        "关键字段缺失，无法比对，转人工核验",
    )


def _names_by_source(app: Application, materials: Sequence[Material]) -> list[ConsistencyValue]:
    """企业名称在各来源中的取值。"""
    values: list[ConsistencyValue] = [_value_of("application", app.company_name)]
    for material in materials:
        category = _category_of(material)
        text = _read_text(material)
        name: str | None = None
        if category == MaterialCategory.BUSINESS_LICENSE:
            name = _extract_license(text)["name"]
        elif category == MaterialCategory.BANK_STATEMENT:
            name = _extract_bank(text)["account_name"]
        elif category == MaterialCategory.FINANCIAL_REPORT:
            name = _extract_financial(text)["name"]
        elif category == MaterialCategory.TAX_RETURN:
            name = _extract_tax(text)["name"]
        elif category == MaterialCategory.CREDIT_AUTH:
            name = _extract_credit_auth(text)["name"]
        if name and isinstance(name, str):
            values.append(_value_of(category, name))
    # 同一来源多份材料只保留首个非重复取值
    seen: set[tuple[str, str]] = set()
    unique: list[ConsistencyValue] = []
    for item in values:
        key = (str(item.source), item.value)
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def _value_of(source: object, value: str) -> ConsistencyValue:
    return ConsistencyValue(source=source, value=value)


def check_consistency(
    app: Application, materials: Sequence[Material]
) -> ConsistencyResult:
    """2.1 材料一致性判断（P1）：主体信息、期间与时效、金额勾稽。"""
    checks: list[ConsistencyCheck] = []

    # C1 企业名称一致
    name_values = _names_by_source(app, materials)
    normalized = {_norm_company(item.value) for item in name_values if item.value}
    if len(name_values) < 2:
        checks.append(
            _uncertain("企业名称一致性", "企业名称", name_values, ConsistencySeverity.HIGH)
        )
    elif len(normalized) == 1:
        checks.append(
            _build_check(
                "企业名称一致性",
                "企业名称",
                name_values,
                ConsistencyStatus.PASS,
                ConsistencySeverity.HIGH,
            )
        )
    else:
        checks.append(
            _build_check(
                "企业名称一致性",
                "企业名称",
                name_values,
                ConsistencyStatus.FAIL,
                ConsistencySeverity.HIGH,
                "各来源企业全称不一致，请以营业执照为准核实",
            )
        )

    # C2 统一社会信用代码一致
    code_values: list[ConsistencyValue] = []
    if app.credit_code:
        code_values.append(_value_of("application", app.credit_code.upper()))
    for material in materials:
        category = _category_of(material)
        text = _read_text(material)
        code: str | None = None
        if category == MaterialCategory.BUSINESS_LICENSE:
            code = _extract_license(text)["credit_code"]
        elif category == MaterialCategory.CREDIT_AUTH:
            code = _extract_credit_auth(text)["credit_code"]
        elif category == MaterialCategory.TAX_RETURN:
            taxpayer_id = _extract_tax(text)["taxpayer_id"]
            # 纳税人识别号仅在与统一社会信用代码同格式（18 位）时参与比对
            code = (
                taxpayer_id
                if isinstance(taxpayer_id, str) and _CREDIT_CODE_RE.fullmatch(taxpayer_id)
                else None
            )
        if code and isinstance(code, str):
            code_values.append(_value_of(category, code.upper()))
    if len(code_values) < 2:
        checks.append(
            _uncertain(
                "统一社会信用代码一致性",
                "统一社会信用代码",
                code_values,
                ConsistencySeverity.HIGH,
            )
        )
    elif len({item.value for item in code_values}) == 1:
        checks.append(
            _build_check(
                "统一社会信用代码一致性",
                "统一社会信用代码",
                code_values,
                ConsistencyStatus.PASS,
                ConsistencySeverity.HIGH,
            )
        )
    else:
        checks.append(
            _build_check(
                "统一社会信用代码一致性",
                "统一社会信用代码",
                code_values,
                ConsistencyStatus.FAIL,
                ConsistencySeverity.HIGH,
                "各来源统一社会信用代码不一致，请核实原件",
            )
        )

    # C5 银行流水期间连续覆盖
    bank_materials = [
        m for m in materials if _category_of(m) == MaterialCategory.BANK_STATEMENT
    ]
    bank_texts = [_read_text(m) for m in bank_materials]
    if not bank_materials:
        checks.append(
            _uncertain(
                "银行流水期间连续性",
                "统计期间",
                [],
                ConsistencySeverity.MEDIUM,
            )
        )
    else:
        months = sorted(_statement_months([t for t in bank_texts if t.strip()]))
        period_values = [
            _value_of(
                MaterialCategory.BANK_STATEMENT,
                f"{material.file_name}：{_period_label(_read_text(material))}",
            )
            for material in bank_materials
        ]
        if not months:
            checks.append(
                _uncertain(
                    "银行流水期间连续性",
                    "统计期间",
                    period_values,
                    ConsistencySeverity.MEDIUM,
                )
            )
        else:
            missing_months = _missing_months(months)
            if missing_months:
                checks.append(
                    _build_check(
                        "银行流水期间连续性",
                        "统计期间",
                        period_values,
                        ConsistencyStatus.FAIL,
                        ConsistencySeverity.MEDIUM,
                        "流水期间不连续，缺失：" + "、".join(missing_months),
                    )
                )
            else:
                checks.append(
                    _build_check(
                        "银行流水期间连续性",
                        "统计期间",
                        period_values,
                        ConsistencyStatus.PASS,
                        ConsistencySeverity.MEDIUM,
                    )
                )

    # C6 财务报表年度与纳税申报所属年度一致
    financial_materials = [
        m for m in materials if _category_of(m) == MaterialCategory.FINANCIAL_REPORT
    ]
    tax_materials = [m for m in materials if _category_of(m) == MaterialCategory.TAX_RETURN]
    financial_years: set[int] = set()
    financial_values: list[ConsistencyValue] = []
    for material in financial_materials:
        period = _extract_financial(_read_text(material))["year"]
        if period is not None:
            year = int(period.group(1))
            financial_years.add(year)
            financial_values.append(
                _value_of(MaterialCategory.FINANCIAL_REPORT, f"{year} 年度")
            )
    tax_years: set[int] = set()
    tax_values: list[ConsistencyValue] = []
    for material in tax_materials:
        period = _extract_tax(_read_text(material))["year"]
        if period is not None:
            year = int(period.group(1))
            tax_years.add(year)
            tax_values.append(_value_of(MaterialCategory.TAX_RETURN, f"{year} 年度"))
    year_values = financial_values + tax_values
    if not financial_years or not tax_years:
        checks.append(
            _uncertain(
                "财务报表年度一致性",
                "报表所属年度",
                year_values,
                ConsistencySeverity.MEDIUM,
            )
        )
    elif financial_years == tax_years:
        checks.append(
            _build_check(
                "财务报表年度一致性",
                "报表所属年度",
                year_values,
                ConsistencyStatus.PASS,
                ConsistencySeverity.MEDIUM,
            )
        )
    else:
        checks.append(
            _build_check(
                "财务报表年度一致性",
                "报表所属年度",
                year_values,
                ConsistencyStatus.FAIL,
                ConsistencySeverity.MEDIUM,
                "财务报表年度与纳税申报所属年度不一致",
            )
        )

    # C7 征信授权时效
    submit_date = (app.submitted_at or app.created_at).date()
    auth_materials = [
        m for m in materials if _category_of(m) == MaterialCategory.CREDIT_AUTH
    ]
    auth_values: list[ConsistencyValue] = []
    auth_expired = False
    auth_signed_missing = False
    for material in auth_materials:
        fields = _extract_credit_auth(_read_text(material))
        signed_at = fields["signed_at"]
        valid_until = fields["valid_until"]
        if isinstance(signed_at, date):
            auth_values.append(
                _value_of(MaterialCategory.CREDIT_AUTH, f"签署日期 {signed_at.isoformat()}")
            )
            if submit_date - signed_at > timedelta(days=AUTH_SIGN_VALID_DAYS):
                auth_expired = True
        else:
            auth_signed_missing = True
        if isinstance(valid_until, date):
            auth_values.append(
                _value_of(
                    MaterialCategory.CREDIT_AUTH, f"授权有效期至 {valid_until.isoformat()}"
                )
            )
            if valid_until < submit_date:
                auth_expired = True
        auth_values.append(
            _value_of("application", f"申请提交日期 {submit_date.isoformat()}")
        )
    if not auth_materials or auth_signed_missing:
        checks.append(
            _uncertain(
                "征信授权书时效", "签署日期", auth_values, ConsistencySeverity.HIGH
            )
        )
    elif auth_expired:
        checks.append(
            _build_check(
                "征信授权书时效",
                "签署日期",
                auth_values,
                ConsistencyStatus.FAIL,
                ConsistencySeverity.HIGH,
                f"授权书签署超过 {AUTH_SIGN_VALID_MONTHS} 个月或授权期限已过，需重新签署",
            )
        )
    else:
        checks.append(
            _build_check(
                "征信授权书时效",
                "签署日期",
                auth_values,
                ConsistencyStatus.PASS,
                ConsistencySeverity.HIGH,
            )
        )

    # C9 材料日期不得晚于申请提交日期
    date_values: list[ConsistencyValue] = []
    future_sources: list[str] = []
    for material in materials:
        category = _category_of(material)
        text = _read_text(material)
        material_date: date | None = None
        if category == MaterialCategory.BANK_STATEMENT:
            material_date = _period_end(text)
        elif category == MaterialCategory.FINANCIAL_REPORT:
            material_date = _extract_financial(text)["period_end"]
        elif category == MaterialCategory.TAX_RETURN:
            material_date = _extract_tax(text)["period_end"]
        elif category == MaterialCategory.CREDIT_AUTH:
            signed_at = _extract_credit_auth(text)["signed_at"]
            material_date = signed_at if isinstance(signed_at, date) else None
        if isinstance(material_date, date):
            label = f"{CATEGORY_LABELS[category]} · {material.file_name}"
            date_values.append(_value_of(category, f"{label} 截止 {material_date.isoformat()}"))
            if material_date > submit_date + timedelta(days=1):
                future_sources.append(f"{CATEGORY_LABELS[category]}（{material_date.isoformat()}）")
    if not date_values:
        checks.append(
            _uncertain(
                "材料日期时效", "材料所属日期", date_values, ConsistencySeverity.LOW
            )
        )
    elif future_sources:
        checks.append(
            _build_check(
                "材料日期时效",
                "材料所属日期",
                date_values,
                ConsistencyStatus.FAIL,
                ConsistencySeverity.HIGH,
                "材料日期晚于申请提交日期：" + "、".join(sorted(set(future_sources))),
            )
        )
    else:
        checks.append(
            _build_check(
                "材料日期时效",
                "材料所属日期",
                date_values,
                ConsistencyStatus.PASS,
                ConsistencySeverity.MEDIUM,
            )
        )

    # C14 银行流水勾稽：期初 + 本月收入 - 本月支出 = 期末
    ledger_values: list[ConsistencyValue] = []
    ledger_failures: list[str] = []
    ledger_compared = 0
    for material in bank_materials:
        fields = _extract_bank(_read_text(material))
        opening = fields["opening"]
        closing = fields["closing"]
        income = fields["income"]
        expense = fields["expense"]
        if None in (opening, closing, income, expense):
            continue
        ledger_compared += 1
        expected = float(opening) + float(income) - float(expense)
        if abs(expected - float(closing)) > AMOUNT_TOLERANCE:
            ledger_failures.append(
                f"{material.file_name}：{float(opening):,.2f}+{float(income):,.2f}"
                f"-{float(expense):,.2f}={expected:,.2f}，期末为{float(closing):,.2f}"
            )
    if ledger_failures:
        ledger_values = [
            _value_of(MaterialCategory.BANK_STATEMENT, detail) for detail in ledger_failures
        ]
        checks.append(
            _build_check(
                "银行流水勾稽",
                "期初/收入/支出/期末",
                ledger_values,
                ConsistencyStatus.FAIL,
                ConsistencySeverity.HIGH,
                "流水借贷与余额不平，需核实原始对账单",
            )
        )
    elif ledger_compared:
        checks.append(
            _build_check(
                "银行流水勾稽",
                "期初/收入/支出/期末",
                [],
                ConsistencyStatus.PASS,
                ConsistencySeverity.HIGH,
            )
        )
    else:
        checks.append(
            _uncertain(
                "银行流水勾稽",
                "期初/收入/支出/期末",
                [],
                ConsistencySeverity.HIGH,
            )
        )

    # C15 资产负债表恒等式：资产总计 = 负债合计 + 所有者权益合计
    balance_values: list[ConsistencyValue] = []
    balance_status = ConsistencyStatus.UNCERTAIN
    balance_suggestion: str | None = None
    for material in financial_materials:
        fields = _extract_financial(_read_text(material))
        if not fields["has_balance_sheet"]:
            continue
        assets = fields["assets"]
        liabilities = fields["liabilities"]
        equity = fields["equity"]
        if None in (assets, liabilities, equity):
            continue
        balance_values = [
            _value_of(MaterialCategory.FINANCIAL_REPORT, f"资产总计 {float(assets):,.2f}"),
            _value_of(MaterialCategory.FINANCIAL_REPORT, f"负债合计 {float(liabilities):,.2f}"),
            _value_of(MaterialCategory.FINANCIAL_REPORT, f"所有者权益合计 {float(equity):,.2f}"),
        ]
        gap = float(assets) - float(liabilities) - float(equity)
        if abs(gap) > AMOUNT_TOLERANCE:
            balance_status = ConsistencyStatus.FAIL
            balance_suggestion = f"资产与负债+所有者权益差额 {gap:,.2f} 元，报表不平"
        else:
            balance_status = ConsistencyStatus.PASS
        break
    checks.append(
        _build_check(
            "资产负债表勾稽",
            "资产 = 负债 + 所有者权益",
            balance_values,
            balance_status,
            ConsistencySeverity.HIGH,
            balance_suggestion,
        )
    )
    if balance_status == ConsistencyStatus.UNCERTAIN and balance_values == []:
        checks[-1] = _uncertain(
            "资产负债表勾稽",
            "资产 = 负债 + 所有者权益",
            [],
            ConsistencySeverity.HIGH,
        )

    is_consistent = not any(
        check.status == ConsistencyStatus.FAIL
        and check.severity == ConsistencySeverity.HIGH
        for check in checks
    )
    return ConsistencyResult(is_consistent=is_consistent, checks=checks)


def _period_label(text: str) -> str:
    """流水统计期间的文本标签，无法识别时标注。"""
    match = _PERIOD_RE.search(text)
    if not match:
        return "期间未识别"
    return (
        f"{match.group(1)}-{int(match.group(2)):02d} 至 "
        f"{match.group(3)}-{int(match.group(4)):02d}"
    )


def _missing_months(months: Sequence[tuple[int, int]]) -> list[str]:
    """找出年月序列中缺失的月份。"""
    if not months:
        return []
    start_year, start_month = months[0]
    end_year, end_month = months[-1]
    existing = set(months)
    missing: list[str] = []
    year, month = start_year, start_month
    while (year, month) <= (end_year, end_month):
        if (year, month) not in existing:
            missing.append(f"{year}-{month:02d}")
        month += 1
        if month > 12:
            year, month = year + 1, 1
    return missing


# ---------------------------------------------------------------- 准入规则匹配

# 营业执照成立日期，如「成立日期2019年08月28日」
_ESTABLISHED_RE = re.compile(
    r"成立日期\s*[：:]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
# 营业期限，用于执照未直接标注登记状态时兜底推断存续/到期
_BUSINESS_TERM_RE = re.compile(
    r"营业期限\s*[：:]?\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*至\s*"
    r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日"
)
# 统一社会信用代码校验字符集与加权因子（GB 32100）
_CREDIT_CODE_CHARSET = "0123456789ABCDEFGHJKLMNPQRTUWXY"
_CREDIT_CODE_WEIGHTS = (1, 3, 9, 27, 19, 26, 16, 17, 20, 29, 25, 13, 8, 24, 10, 30, 28)

# 抵押物评估价值标签
_COLLATERAL_LABELS = ("评估价值", "评估值", "抵押价值", "评估金额")
_TECH_CERT_KEYWORDS = (
    "高新技术企业",
    "专精特新",
    "知识产权",
    "发明专利",
    "软件著作权",
    "科技型中小企业",
)
_IP_KEYWORDS = ("发明专利", "软件著作权", "实用新型", "商标")
_COLLATERAL_KEYWORDS = (
    "抵押合同",
    "抵押物",
    "评估报告",
    "房地产权证",
    "房产证",
    "不动产",
    "租赁合同",
)

_ACTION_TO_CONCLUSION = {
    "reject": AiConclusion.FORBIDDEN,
    "manual": AiConclusion.MANUAL,
    "attention": AiConclusion.ATTENTION,
    "pass": AiConclusion.PASS,
}

_OPERATOR_LABELS = {
    "eq": "=",
    "neq": "≠",
    "gt": ">",
    "gte": "≥",
    "lt": "<",
    "lte": "≤",
    "in": "属于",
    "not_in": "不属于",
    "contains": "包含",
}


@dataclass
class RuleField:
    """规则字段的取值、证据来源与展示文本。"""

    value: object
    source: str | None = None
    display: str | None = None


def _months_between(start: date, end: date) -> int:
    """两个日期相差的完整月数。"""
    return (end.year - start.year) * 12 + (end.month - start.month)


def _license_status(text: str) -> str | None:
    """从营业执照识别登记状态；未直接标注时按营业期限兜底推断。"""
    compact = _compact(text)
    for status in ("存续", "在营", "开业", "吊销", "注销", "迁出", "非正常"):
        if status in compact:
            return status
    match = _BUSINESS_TERM_RE.search(text)
    if not match:
        return None
    end_year, end_month, end_day = (int(group) for group in match.groups()[3:])
    try:
        term_end = date(end_year, end_month, end_day)
    except ValueError:
        return None
    return "存续" if term_end >= date.today() else "营业期限已届满"


def _license_established_months(text: str, ref_date: date) -> int | None:
    """营业执照成立日期至参考日期的月数。"""
    match = _ESTABLISHED_RE.search(text)
    if not match:
        return None
    try:
        started_at = date(*(int(group) for group in match.groups()))
    except ValueError:
        return None
    return max(_months_between(started_at, ref_date), 0)


def _credit_code_valid(code: str | None) -> bool | None:
    """校验统一社会信用代码：18 位且校验位合法。"""
    if not code:
        return None
    normalized = code.strip().upper()
    if len(normalized) != 18 or any(ch not in _CREDIT_CODE_CHARSET for ch in normalized):
        return False
    total = sum(
        _CREDIT_CODE_CHARSET.index(ch) * weight
        for ch, weight in zip(normalized[:17], _CREDIT_CODE_WEIGHTS)
    )
    check_value = 31 - total % 31
    if check_value == 31:
        check_value = 0
    return normalized[-1] == _CREDIT_CODE_CHARSET[check_value]


def _texts_by_category(
    materials: Sequence[Material], category: MaterialCategory
) -> list[str]:
    return [
        text
        for text in (_read_text(material) for material in materials if _category_of(material) == category)
        if text.strip()
    ]


def _financial_snapshot(texts: Sequence[str]) -> dict[str, float | None]:
    """汇总财报中的营收、利润、资产负债、货币资金与经营现金流。"""
    snapshot: dict[str, float | None] = {
        "revenue": None,
        "profit": None,
        "net_profit": None,
        "assets": None,
        "liabilities": None,
        "equity": None,
        "cash": None,
        "operating_cash": None,
    }
    for text in texts:
        fields = _extract_financial(text)
        for key in ("revenue", "profit", "assets", "liabilities", "equity"):
            value = fields.get(key)
            if snapshot[key] is None and isinstance(value, (int, float)):
                snapshot[key] = float(value)
        cash = _amounts_after(text, "货币资金", 2)
        if snapshot["cash"] is None and cash:
            snapshot["cash"] = float(cash[-1])
        net_profit = _amounts_after(text, "净利润", 1)
        if snapshot["net_profit"] is None and net_profit:
            snapshot["net_profit"] = float(net_profit[0])
        operating_cash = _amounts_after(text, "经营活动产生的现金流量净额", 1)
        if snapshot["operating_cash"] is None and operating_cash:
            snapshot["operating_cash"] = float(operating_cash[0])
    return snapshot


def _bank_entries(
    materials: Sequence[Material],
) -> list[tuple[tuple[int, int] | None, float, float | None, float | None]]:
    """逐份流水提取（所属年月、贷方发生额、借方发生额、期末余额）。"""
    entries: list[tuple[tuple[int, int] | None, float, float | None, float | None]] = []
    for material in materials:
        if _category_of(material) != MaterialCategory.BANK_STATEMENT:
            continue
        text = _read_text(material)
        totals = _amounts_after(text, "本月合计", 3)
        if not totals:
            continue
        period = _PERIOD_RE.search(text)
        month = (int(period.group(1)), int(period.group(2))) if period else None
        entries.append(
            (
                month,
                float(totals[0]),
                float(totals[1]) if len(totals) > 1 else None,
                _amount_after_label(text, "期末余额"),
            )
        )
    entries.sort(key=lambda item: item[0] or (0, 0))
    return entries


def _longest_consecutive_months(months: Sequence[tuple[int, int]]) -> int:
    """无断月覆盖的最长连续月数。"""
    points = sorted(set(months))
    if not points:
        return 0
    longest = current = 1
    for previous, current_point in zip(points, points[1:]):
        gap = (current_point[0] - previous[0]) * 12 + (current_point[1] - previous[1])
        current = current + 1 if gap == 1 else 1
        longest = max(longest, current)
    return longest


def _max_consecutive_outflow(
    entries: Sequence[tuple[tuple[int, int] | None, float, float | None, float | None]],
) -> int:
    """连续「借方发生额 > 贷方发生额」的最长月数。"""
    longest = current = 0
    for _, income, expense, _closing in entries:
        if expense is not None and expense > income:
            current += 1
            longest = max(longest, current)
        else:
            current = 0
    return longest


def _keyword_count(texts: Sequence[str], keywords: Sequence[str]) -> int:
    return sum(
        _compact(text).count(keyword) for text in texts for keyword in keywords
    )


def _collateral_value(texts: Sequence[str]) -> float | None:
    """从抵押物评估材料中读取评估价值（元）。"""
    for text in texts:
        for label in _COLLATERAL_LABELS:
            match = re.search(
                label + r"[：:\s]*([\d,]+(?:\.\d+)?)\s*(万元)?", text
            )
            if not match:
                continue
            value = _to_amount(match.group(1))
            return value * 10000 if match.group(2) else value
    return None


def _ratio_field(
    numerator: float | None, denominator: float | None, source: str
) -> RuleField:
    if numerator is None or denominator is None or denominator <= 0:
        return RuleField(None, source)
    ratio = numerator / denominator
    return RuleField(ratio, source, f"{ratio:.2%}")


def build_rule_fields(
    app: Application,
    materials: Sequence[Material],
    consistency: ConsistencyResult,
) -> dict[str, RuleField]:
    """按规则文件 field 定义，汇总申请与材料 OCR 的字段取值。"""
    submit_date = (app.submitted_at or app.created_at).date()
    amount = float(app.amount)
    fields: dict[str, RuleField] = {
        "apply_amount": RuleField(amount, "application", f"{amount:,.2f} 万元")
    }

    # 营业执照：登记状态、成立年限、信用代码格式
    license_texts = _texts_by_category(materials, MaterialCategory.BUSINESS_LICENSE)
    if license_texts:
        license_text = license_texts[0]
        status = _license_status(license_text)
        fields["registration_status"] = RuleField(
            status, MaterialCategory.BUSINESS_LICENSE.value, status
        )
        established = _license_established_months(license_text, submit_date)
        fields["established_months"] = RuleField(
            established,
            MaterialCategory.BUSINESS_LICENSE.value,
            f"{established} 个月" if established is not None else None,
        )
        code = _extract_license(license_text)["credit_code"] or app.credit_code
        valid = _credit_code_valid(code)
        code_text = {True: "valid", False: "invalid"}.get(valid) if valid is not None else None
        fields["credit_code_format"] = RuleField(
            code_text,
            MaterialCategory.BUSINESS_LICENSE.value,
            "有效" if valid else "无效" if valid is False else None,
        )
    else:
        for name in ("registration_status", "established_months", "credit_code_format"):
            fields[name] = RuleField(None, MaterialCategory.BUSINESS_LICENSE.value)

    # 征信授权书：授权剩余有效期月数；无明确到期日时按签署后 6 个月计
    auth_texts = _texts_by_category(materials, MaterialCategory.CREDIT_AUTH)
    auth_months: list[int] = []
    for text in auth_texts:
        info = _extract_credit_auth(text)
        signed_at = info["signed_at"]
        valid_until = info["valid_until"]
        if isinstance(valid_until, date):
            months = (
                -1
                if valid_until < submit_date
                else _months_between(submit_date, valid_until)
            )
        elif isinstance(signed_at, date):
            months = AUTH_SIGN_VALID_MONTHS - _months_between(signed_at, submit_date)
        else:
            continue
        auth_months.append(months)
    auth_valid = min(auth_months) if auth_months else None
    fields["auth_valid_months"] = RuleField(
        auth_valid,
        MaterialCategory.CREDIT_AUTH.value,
        (
            "授权期限已过"
            if auth_valid is not None and auth_valid < 0
            else f"{auth_valid} 个月（剩余有效期）"
            if auth_valid is not None
            else None
        ),
    )

    # 银行流水：覆盖月数、连续净流出、6 个月贷方合计
    bank_texts = _texts_by_category(materials, MaterialCategory.BANK_STATEMENT)
    entries = _bank_entries(materials)
    if bank_texts:
        coverage = _longest_consecutive_months(_statement_months(bank_texts))
        fields["statement_coverage_months"] = RuleField(
            coverage, MaterialCategory.BANK_STATEMENT.value, f"{coverage} 个月"
        )
        fields["consecutive_outflow_months"] = RuleField(
            _max_consecutive_outflow(entries),
            MaterialCategory.BANK_STATEMENT.value,
            f"{_max_consecutive_outflow(entries)} 个月",
        )
        inflow_total: float | None = sum(entry[1] for entry in entries)
        inflow_6m: float | None = (
            sum(entry[1] for entry in entries[-6:]) if entries else None
        )
        closings = [entry[3] for entry in entries if entry[3] is not None]
        closing = float(closings[-1]) if closings else None
    else:
        inflow_total = inflow_6m = closing = None
        for name in ("statement_coverage_months", "consecutive_outflow_months"):
            fields[name] = RuleField(None, MaterialCategory.BANK_STATEMENT.value)

    # 财务报表：营收、利润、资产负债、货币资金
    financial_texts = _texts_by_category(materials, MaterialCategory.FINANCIAL_REPORT)
    snapshot = _financial_snapshot(financial_texts)
    revenue = snapshot["revenue"]
    net_profit = (
        snapshot["net_profit"]
        if snapshot["net_profit"] is not None
        else snapshot["profit"]
    )
    fields["net_profit"] = RuleField(
        net_profit,
        MaterialCategory.FINANCIAL_REPORT.value,
        f"{net_profit:,.2f} 元" if net_profit is not None else None,
    )
    fields["debt_ratio"] = _ratio_field(
        snapshot["liabilities"], snapshot["assets"], MaterialCategory.FINANCIAL_REPORT.value
    )
    fields["annual_inflow_ratio"] = _ratio_field(
        inflow_total, revenue, MaterialCategory.BANK_STATEMENT.value
    )
    fields["inflow_to_revenue"] = _ratio_field(
        inflow_6m, revenue, MaterialCategory.BANK_STATEMENT.value
    )
    fields["loan_to_revenue"] = _ratio_field(
        amount * 10000, revenue, MaterialCategory.FINANCIAL_REPORT.value
    )
    net_asset = (
        snapshot["assets"] - snapshot["liabilities"]
        if snapshot["assets"] is not None and snapshot["liabilities"] is not None
        else None
    )
    fields["loan_to_net_asset"] = _ratio_field(
        amount * 10000, net_asset, MaterialCategory.FINANCIAL_REPORT.value
    )
    fields["loan_to_inflow_6m"] = _ratio_field(
        amount * 10000, inflow_6m, MaterialCategory.BANK_STATEMENT.value
    )
    if closing is not None and snapshot["cash"]:
        fields["cash_diff_ratio"] = _ratio_field(
            abs(closing - snapshot["cash"]),
            snapshot["cash"],
            MaterialCategory.BANK_STATEMENT.value,
        )
    else:
        fields["cash_diff_ratio"] = RuleField(None, MaterialCategory.BANK_STATEMENT.value)
    cashflow_positive = None
    if net_profit is not None or snapshot["operating_cash"] is not None:
        cashflow_positive = (net_profit or 0) > 0 or (snapshot["operating_cash"] or 0) > 0
    fields["profit_or_cashflow_positive"] = RuleField(
        cashflow_positive,
        MaterialCategory.FINANCIAL_REPORT.value,
        None if cashflow_positive is None else "是" if cashflow_positive else "否",
    )

    # 纳税申报表：重大欠税、研发费用加计扣除
    tax_texts = _texts_by_category(materials, MaterialCategory.TAX_RETURN)
    if tax_texts:
        compact_tax = "".join(_compact(text) for text in tax_texts)
        no_debt = "无欠税" in compact_tax or "不存在欠税" in compact_tax
        has_debt = not no_debt and ("欠税" in compact_tax or "欠缴税款" in compact_tax)
        fields["has_major_tax_debt"] = RuleField(
            has_debt, MaterialCategory.TAX_RETURN.value, "是" if has_debt else "否"
        )
        has_rd = "加计扣除" in compact_tax or "高新技术企业" in compact_tax
        fields["has_rd_deduction"] = RuleField(
            has_rd, MaterialCategory.TAX_RETURN.value, "是" if has_rd else "否"
        )
    else:
        for name in ("has_major_tax_debt", "has_rd_deduction"):
            fields[name] = RuleField(None, MaterialCategory.TAX_RETURN.value)

    # 其他材料：科技资质、知识产权、抵押物证明
    other_texts = _texts_by_category(materials, MaterialCategory.OTHER)
    if other_texts:
        ip_count = _keyword_count(other_texts, _IP_KEYWORDS)
        has_tech = _keyword_count(other_texts, _TECH_CERT_KEYWORDS) > 0 or ip_count > 0
        has_collateral = _keyword_count(other_texts, _COLLATERAL_KEYWORDS) > 0
        fields["has_tech_cert"] = RuleField(
            has_tech, MaterialCategory.OTHER.value, "是" if has_tech else "否"
        )
        fields["ip_count"] = RuleField(
            ip_count, MaterialCategory.OTHER.value, f"{ip_count} 项"
        )
        fields["has_collateral_doc"] = RuleField(
            has_collateral, MaterialCategory.OTHER.value, "是" if has_collateral else "否"
        )
        fields["loan_to_collateral"] = _ratio_field(
            amount * 10000, _collateral_value(other_texts), MaterialCategory.OTHER.value
        )
    else:
        for name in ("has_tech_cert", "ip_count", "has_collateral_doc", "loan_to_collateral"):
            fields[name] = RuleField(None, MaterialCategory.OTHER.value)

    # 企业名称一致性：复用一致性校验结论
    name_check = next(
        (check for check in consistency.checks if check.check_item == "企业名称一致性"),
        None,
    )
    if name_check is not None and name_check.status != ConsistencyStatus.UNCERTAIN:
        consistent = name_check.status == ConsistencyStatus.PASS
        fields["company_name_consistent"] = RuleField(
            consistent, "application", "一致" if consistent else "不一致"
        )
    else:
        fields["company_name_consistent"] = RuleField(None, "application")

    return fields


def _format_value(value: object) -> str:
    if isinstance(value, bool):
        return "是" if value else "否"
    if isinstance(value, float):
        if 0 < abs(value) <= 1:
            return f"{value:.0%}"
        return str(int(value)) if value.is_integer() else f"{value:g}"
    return str(value)


def _format_score(score: float) -> str:
    return str(int(score)) if float(score).is_integer() else f"{score:g}"


def _expectation_text(operator: str, expected: object) -> str:
    """把 YAML 规则要求转成可读表达式。"""
    if operator in ("in", "not_in"):
        values = expected if isinstance(expected, (list, tuple)) else [expected]
        return f"{_OPERATOR_LABELS[operator]} {'/'.join(_format_value(item) for item in values)}"
    if operator == "contains":
        return f"包含 {_format_value(expected)}"
    return f"{_OPERATOR_LABELS.get(operator, operator)} {_format_value(expected)}"


def _compare(actual: object, operator: str, expected: object) -> bool | None:
    """按操作符比较实际值与期望值，无法比较时返回 None。"""
    if operator == "in":
        return actual in (expected or [])
    if operator == "not_in":
        return actual not in (expected or [])
    if operator == "contains":
        return str(expected) in str(actual)
    if operator == "eq":
        if isinstance(actual, bool) or isinstance(expected, bool):
            return bool(actual) == bool(expected)
        return actual == expected
    if operator == "neq":
        matched = _compare(actual, "eq", expected)
        return None if matched is None else not matched
    try:
        left, right = float(actual), float(expected)
    except (TypeError, ValueError):
        return None
    if operator == "gt":
        return left > right
    if operator == "gte":
        return left >= right
    if operator == "lt":
        return left < right
    if operator == "lte":
        return left <= right
    return None


def _level_of(score: float, scoring: dict) -> str:
    for name, bounds in (scoring.get("level_thresholds") or {}).items():
        try:
            low, high = float(bounds[0]), float(bounds[1])
        except (TypeError, ValueError, IndexError):
            continue
        if low <= score <= high:
            return str(name)
    return "D"


def evaluate_rules(config: dict, fields: dict[str, RuleField]) -> RuleMatchResult:
    """按规则文件逐条判定，并计算准入评分与等级。"""
    scoring = config.get("scoring") or {}
    rules = [rule for rule in (config.get("rules") or []) if isinstance(rule, dict)]
    items: list[RuleMatchItem] = []
    hard_fail_count = soft_fail_count = uncertain_count = pass_count = 0

    for rule in rules:
        rule_id = str(rule.get("rule_id") or "")
        kind = "hard" if rule.get("kind") == "hard" else "soft"
        operator = str(rule.get("operator") or "eq")
        expected = rule.get("value")
        field_name = str(rule.get("field") or "")
        field = fields.get(field_name)
        actual_value = field.value if field is not None else None
        expected_text = _expectation_text(operator, expected)

        matched = (
            None if actual_value is None else _compare(actual_value, operator, expected)
        )
        if matched is None:
            result = RuleMatchStatus.UNCERTAIN
            uncertain_count += 1
            detail = f"{rule.get('detail_zh') or ''}（关键证据缺失，转人工核验）"
        elif matched:
            result = RuleMatchStatus.PASS
            pass_count += 1
            detail = str(rule.get("detail_zh") or "")
        else:
            result = RuleMatchStatus.FAIL
            if kind == "hard":
                hard_fail_count += 1
            else:
                soft_fail_count += 1
            detail = str(rule.get("detail_zh") or "")

        if isinstance(actual_value, bool):
            evidence_value: str | float | int | None = "是" if actual_value else "否"
        elif isinstance(actual_value, (str, int, float)):
            evidence_value = actual_value
        else:
            evidence_value = None

        items.append(
            RuleMatchItem(
                rule_id=rule_id,
                rule_name=str(rule.get("rule_name") or ""),
                kind=kind,
                operator=operator,
                expected=expected_text,
                actual=field.display if field is not None else None,
                result=result,
                evidence=RuleEvidence(
                    source=field.source if field is not None else None,
                    field=field_name,
                    value=evidence_value,
                ),
                detail=detail.strip() or None,
            )
        )

    base_score = float(scoring.get("base_score") or 0)
    soft_unit = float(scoring.get("soft_rule_score") or 0)
    soft_pass_count = sum(
        1 for item in items if item.kind == "soft" and item.result == RuleMatchStatus.PASS
    )
    if hard_fail_count and scoring.get("hard_rules_reject", True):
        score = 0.0
    else:
        score = min(100.0, base_score + soft_pass_count * soft_unit)
    level = _level_of(score, scoring)

    return RuleMatchResult(
        rule_version=str(config.get("version") or "unknown"),
        score=round(score, 2),
        level=level,
        level_label=(scoring.get("level_label") or {}).get(level),
        level_note=(scoring.get("level_note") or {}).get(level),
        pass_count=pass_count,
        total_count=len(items),
        hard_fail_count=hard_fail_count,
        soft_fail_count=soft_fail_count,
        uncertain_count=uncertain_count,
        rules=items,
    )


def match_rules(
    app: Application,
    materials: Sequence[Material],
    consistency: ConsistencyResult,
    config: dict | None = None,
) -> RuleMatchResult:
    """2.2 准入规则匹配：按产品 YAML 逐条输出 pass / fail / uncertain 及证据。"""
    rule_config = config or load_rule_config(app.product)
    if not rule_config:
        return RuleMatchResult(rule_version="unknown", pass_count=0, total_count=0)
    fields = build_rule_fields(app, materials, consistency)
    return evaluate_rules(rule_config, fields)


def summarize_risk_signals(
    completeness: CompletenessResult,
    consistency: ConsistencyResult,
    rule_matching: RuleMatchResult,
) -> RiskSummary:
    """2.3 风险信号汇总：结合完整性与规则匹配结果输出分级风险信号。"""
    signals: list[RiskSignal] = []

    def add(
        level: RiskLevel,
        category: str,
        title: str,
        source: str | None,
        detail: str,
        suggestion: str | None = None,
    ) -> None:
        signals.append(
            RiskSignal(
                signal_id=f"RS-{len(signals) + 1:02d}",
                level=level,
                category=category,
                title=title[:200],
                evidence=RiskEvidence(source=source, detail=detail[:500]),
                suggestion=suggestion,
            )
        )

    for item in rule_matching.rules:
        if item.result != RuleMatchStatus.FAIL:
            continue
        evidence_source = item.evidence.source if item.evidence else None
        detail = (
            f"{item.rule_id}：实际 {item.actual or '—'}，要求 {item.expected or '—'}"
            f"；{item.detail or ''}"
        )
        if item.kind == "hard":
            add(
                RiskLevel.HIGH,
                "准入规则",
                item.rule_name,
                evidence_source,
                detail,
                "强规则未通过，建议拒绝",
            )
        else:
            add(
                RiskLevel.MEDIUM,
                "经营与财务",
                item.rule_name,
                evidence_source,
                detail,
                "弱规则未通过，建议人工关注并核实",
            )

    for check in consistency.checks:
        if check.status != ConsistencyStatus.FAIL:
            continue
        if check.severity == ConsistencySeverity.HIGH:
            level = RiskLevel.HIGH
        elif check.severity == ConsistencySeverity.MEDIUM:
            level = RiskLevel.MEDIUM
        else:
            level = RiskLevel.LOW
        add(
            level,
            "材料一致性",
            check.check_item,
            None,
            check.suggestion or f"{check.check_item}不一致",
            "转人工核验原始材料",
        )

    for issue in completeness.issues:
        add(RiskLevel.MEDIUM, "材料完整性", issue.message, None, issue.message, "补件后重新预审")

    return RiskSummary(risk_signals=signals)


def collect_conflicts(
    materials: Sequence[Material],
    consistency: ConsistencyResult,
    rule_matching: RuleMatchResult,
) -> ConflictSummary:
    """2.4 低置信 / 规则冲突项：低置信材料、严重不一致与证据不足规则。"""
    conflicts: list[ConflictItem] = []

    for material in materials:
        confidence = (
            float(material.confidence) if material.confidence is not None else None
        )
        if confidence is not None and confidence < LOW_CONFIDENCE_THRESHOLD:
            conflicts.append(
                ConflictItem(
                    type=ConflictType.LOW_CONFIDENCE,
                    source=material.category,
                    value=material.file_name,
                    confidence=confidence,
                    reason=(
                        f"材料分类置信度 {confidence:.2f} 低于阈值 "
                        f"{LOW_CONFIDENCE_THRESHOLD}，需人工确认类别"
                    ),
                )
            )

    for check in consistency.checks:
        if check.status != ConsistencyStatus.FAIL:
            continue
        conflicts.append(
            ConflictItem(
                type=ConflictType.DATA_INCONSISTENT,
                field=check.field,
                value="；".join(item.value for item in check.values[:3]) or None,
                reason=check.suggestion or f"{check.check_item}不一致，需人工核验",
            )
        )

    for item in rule_matching.rules:
        if item.result != RuleMatchStatus.UNCERTAIN:
            continue
        conflicts.append(
            ConflictItem(
                type=ConflictType.RULE_CONFLICT,
                source=item.evidence.source if item.evidence else None,
                field=item.evidence.field if item.evidence else None,
                rules=[item.rule_id],
                reason=f"规则 {item.rule_id}（{item.rule_name}）缺少判定证据，需人工核验",
            )
        )

    return ConflictSummary(conflicts=conflicts)


def build_summary(
    completeness: CompletenessResult,
    consistency: ConsistencyResult,
    rule_matching: RuleMatchResult,
    config: dict | None = None,
) -> AiReportSummary:
    """3 汇总结论：按规则文件 conclusion_logic 推导结论、摘要与通过率。"""
    logic = (config or {}).get("conclusion_logic") or {}

    def action(key: str, default: str) -> str:
        return str(logic.get(key) or default)

    high_fails = [
        check
        for check in consistency.checks
        if check.status == ConsistencyStatus.FAIL
        and check.severity == ConsistencySeverity.HIGH
    ]
    hard_fails = [
        item
        for item in rule_matching.rules
        if item.kind == "hard" and item.result == RuleMatchStatus.FAIL
    ]
    soft_fails = [
        item
        for item in rule_matching.rules
        if item.kind == "soft" and item.result == RuleMatchStatus.FAIL
    ]
    # 缺件 / 不可读属于需补件的阻断性完整性问题；期间、三表等异常仅需关注
    completeness_blocking = bool(completeness.missing) or any(
        issue.type in ("missing", "unreadable") for issue in completeness.issues
    )

    if hard_fails and action("hard_rule_fail", "reject") == "reject":
        conclusion = AiConclusion.FORBIDDEN
    elif completeness_blocking:
        conclusion = _ACTION_TO_CONCLUSION.get(
            action("completeness_issue", "manual"), AiConclusion.MANUAL
        )
    elif high_fails:
        conclusion = _ACTION_TO_CONCLUSION.get(
            action("consistency_high_fail", "attention"), AiConclusion.ATTENTION
        )
    elif rule_matching.soft_fail_count >= 3:
        conclusion = _ACTION_TO_CONCLUSION.get(
            action("soft_rule_fail_count_ge_3", "attention"), AiConclusion.ATTENTION
        )
    elif completeness.issues:
        conclusion = AiConclusion.ATTENTION
    else:
        conclusion = _ACTION_TO_CONCLUSION.get(
            action("else", "pass"), AiConclusion.PASS
        )

    parts: list[str] = []
    if rule_matching.total_count:
        parts.append(
            f"准入规则通过 {rule_matching.pass_count}/{rule_matching.total_count} 条，"
            f"评分 {_format_score(rule_matching.score)} 分"
            f"（{rule_matching.level}·{rule_matching.level_label or '—'}）"
        )
    if hard_fails:
        parts.append("强规则未通过：" + "、".join(item.rule_name for item in hard_fails))
    if soft_fails:
        parts.append("弱规则未通过：" + "、".join(item.rule_name for item in soft_fails))
    parts.extend(issue.message for issue in completeness.issues)
    if high_fails:
        parts.append("一致性高风险：" + "、".join(check.check_item for check in high_fails))
    summary_text = (
        "；".join(parts) if parts else "必备材料齐全、内容可读，准入规则与一致性校验通过"
    )

    pass_rate = (
        rule_matching.score
        if rule_matching.total_count
        else round(completeness.coverage_rate * 100, 2)
    )
    return AiReportSummary(
        conclusion=conclusion, summary=summary_text, pass_rate=pass_rate
    )
