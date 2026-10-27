"""AI 材料分析服务。"""

import re
from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

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
    ConflictSummary,
    ConsistencyCheck,
    ConsistencyResult,
    ConsistencySeverity,
    ConsistencyStatus,
    ConsistencyValue,
    DEFAULT_REQUIRED_CATEGORIES,
    MaterialAnalysisRequest,
    MaterialAnalysisResponse,
    RiskSummary,
    RuleMatchResult,
)
from app.schemas.ai_classification import (
    CATEGORY_LABELS,
    MaterialCategory,
    MaterialClassifyInput,
    MimeType,
)
from app.services.classifier import load_text

# ---------------------------------------------------------------- 完整性规则

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


def analyze_completeness(materials: Sequence[Material]) -> CompletenessResult:
    """2.1 材料完整性判断。

    判定规则：
    1. 每类必备材料至少 1 份（营业执照、银行流水、财务报表、纳税申报表、征信授权书）；
    2. 内容可读：OCR 文本为空视为内容不完整，需重传；
    3. 特殊要求：银行流水需覆盖超过 6 个月，财务报表需资产负债表、利润表、现金流量表三表齐全。
    """
    counts = {category: 0 for category in MaterialCategory}
    texts: dict[int, str] = {}
    for material in materials:
        counts[_category_of(material)] += 1
        texts[material.id] = _read_text(material)

    required = list(DEFAULT_REQUIRED_CATEGORIES)
    missing = [category for category in required if counts[category] == 0]
    issues: list[CompletenessIssue] = []

    if missing:
        issues.append(
            CompletenessIssue(
                type="missing",
                message="缺少必备材料：" + "、".join(CATEGORY_LABELS[c] for c in missing),
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

    satisfied_required = sum(1 for category in required if counts[category] > 0)
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
                satisfied=counts[category] > 0,
            )
            for category in MaterialCategory
        ],
        issues=issues,
    )


def generate_report(
    db: Session, app: Application, materials: Sequence[Material]
) -> AiReport:
    """材料分类完成后自动执行 AI 预审：生成或更新该申请的预审报告。

    预审包含材料完整性判断与一致性校验（P1），结论映射：
    - 必备材料缺失：manual（需补件后重新预审）
    - 存在完整性异常 / 高严重度不一致：attention
    - 无问题：pass
    """
    completeness = analyze_completeness(materials)
    consistency = check_consistency(app, materials)
    high_conflicts = [
        check
        for check in consistency.checks
        if check.status == ConsistencyStatus.FAIL
        and check.severity == ConsistencySeverity.HIGH
    ]

    if completeness.missing:
        conclusion = AiConclusion.MANUAL
    elif completeness.issues or high_conflicts:
        conclusion = AiConclusion.ATTENTION
    else:
        conclusion = AiConclusion.PASS

    summary_parts = [issue.message for issue in completeness.issues]
    if high_conflicts:
        summary_parts.append(
            "一致性高风险：" + "、".join(check.check_item for check in high_conflicts)
        )
    summary = (
        "；".join(summary_parts)
        if summary_parts
        else "必备材料齐全、内容可读，材料完整性与一致性校验通过"
    )

    report = db.scalar(
        select(AiReport).where(AiReport.app_id == app.id).order_by(AiReport.id.desc())
    )
    if report is None:
        report = AiReport(app_id=app.id, version="v1")
        db.add(report)

    report.conclusion = conclusion
    report.summary = summary
    report.pass_rate = Decimal(str(round(completeness.coverage_rate * 100, 2)))
    report.completeness = completeness.model_dump(mode="json")
    report.consistency = consistency.model_dump(mode="json")

    # 预审完成后推进申请进度：材料不齐 → 待补件；齐全 → 待人工核验
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
        app.status = ApplicationStatus.MANUAL

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


def match_rules(payload: MaterialAnalysisRequest) -> RuleMatchResult:
    """2.2 准入规则匹配：逐条输出 pass / fail / uncertain 及证据。"""
    raise NotImplementedError("准入规则匹配逻辑待实现")


def summarize_risk_signals(
    payload: MaterialAnalysisRequest,
    completeness: CompletenessResult,
    consistency: ConsistencyResult,
    rule_matching: RuleMatchResult,
) -> RiskSummary:
    """2.3 风险信号汇总：结合完整性与规则匹配结果输出分级风险信号。"""
    raise NotImplementedError("风险信号汇总逻辑待实现")


def collect_conflicts(
    payload: MaterialAnalysisRequest,
    completeness: CompletenessResult,
    consistency: ConsistencyResult,
    rule_matching: RuleMatchResult,
) -> ConflictSummary:
    """2.4 低置信 / 规则冲突项：汇总字段低置信、规则互斥与严重不一致项。"""
    raise NotImplementedError("低置信与冲突项识别逻辑待实现")


def build_summary(
    completeness: CompletenessResult,
    consistency: ConsistencyResult,
    rule_matching: RuleMatchResult,
    risk_summary: RiskSummary,
    conflict_summary: ConflictSummary,
) -> AiReportSummary:
    """3 汇总结论：按规则推导 conclusion / summary / pass_rate。"""
    raise NotImplementedError("预审汇总结论生成逻辑待实现")


def analyze_materials(payload: MaterialAnalysisRequest) -> MaterialAnalysisResponse:
    """材料分析总入口：串联 2.1 ~ 2.4 并生成汇总输出。"""
    raise NotImplementedError("材料分析逻辑待实现")
