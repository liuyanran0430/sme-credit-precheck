"""授信助手工具实现（只读）。

分层约束：只调用 repositories 与既有 services，不写 SQL、不改任何业务数据。
应用类工具入口第一行校验 manager_name，不命中统一返回「未找到该申请」。
"""

from __future__ import annotations

import logging
import re
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from sqlalchemy.orm import Session

from app.core.logging import mask_credit_code
from app.models.application import Application
from app.models.enums import ApplicationStatus, UserRole
from app.models.user import User
from app.qa.intent import (
    KB_MATERIAL_REVIEW,
    KB_POLICY,
    KB_RULE_CONFIG,
    PRODUCT_ALIASES,
    RetrievalPlan,
)
from app.qa.retrieval import retrieve_policy_hits
from app.rag.kb_retriever import KnowledgeHit, retrieve_material_hints
from app.repositories import ApplicationRepository, MaterialRepository, ReportRepository, ReviewRepository
from app.schemas.ai_classification import CATEGORY_LABELS, MaterialCategory
from app.services.analyzer import (
    CORE_REQUIRED_CATEGORIES,
    RuleField,
    _credit_code_valid,
    build_rule_fields,
    check_consistency,
    evaluate_rules,
)
from app.services.precheck_summary import (
    build_precheck_summary_view,
    render_precheck_summary_text,
)
from app.services.rule_config import (
    extra_required_categories,
    list_rule_configs,
    load_rule_config,
)

logger = logging.getLogger(__name__)

# 单工具结果最多 800 字，超出截断，避免撑爆上下文
MAX_TOOL_RESULT_CHARS = 800

STATUS_LABELS: dict[str, str] = {
    "check": "待材料检查",
    "precheck": "待 AI 预审",
    "supplement": "待补件",
    "manual": "待人工核验",
    "risk": "待风控复核",
    "approved": "已审批",
    "rejected": "已否决",
}

_NOT_FOUND_MSG = "未找到该申请，或你无权查看该申请。"

_STATUS_ALIASES: dict[str, str] = {
    **{key: key for key in STATUS_LABELS},
    **{label: key for key, label in STATUS_LABELS.items()},
    "待补件": "supplement",
    "补件": "supplement",
    "待人工校验": "manual",
    "人工复核": "manual",
    "风控": "risk",
    "审批通过": "approved",
    "已通过": "approved",
    "已拒绝": "rejected",
    "已否决": "rejected",
}

# 产品一句话特征（与知识库准入规则目录保持一致）
_PRODUCT_FEATURES: dict[str, str] = {
    "普惠小微经营贷": "面向小微企业的普惠经营贷，成立满 2 年、流水覆盖 12 个月，额度按年营收 30% 上限测算",
    "小微快贷": "小额快速审批，成立满 1 年即可，单笔申请金额不超过 300 万",
    "经营性抵押贷": "需要抵押物权属与评估材料，额度可达抵押物评估价值的 70%",
    "科技e贷": "面向高新技术 / 专精特新企业，需科技资质与知识产权，额度按年营收 50% 上限测算",
}

# 知识库检索不可用时的材料审核要点兜底
_CATEGORY_TIPS: dict[MaterialCategory, str] = {
    MaterialCategory.BUSINESS_LICENSE: "需在有效期内，登记状态为存续/在营，含统一社会信用代码",
    MaterialCategory.BANK_STATEMENT: "对公账户流水，需覆盖规则要求的月份且加盖银行章",
    MaterialCategory.FINANCIAL_REPORT: "资产负债表、利润表、现金流量表三表齐全",
    MaterialCategory.TAX_RETURN: "近一年纳税申报表，无重大欠税记录",
    MaterialCategory.CREDIT_AUTH: "法定代表人签字并盖章，签署日期需在近 6 个月内",
    MaterialCategory.OTHER: "按产品要求提供补充证明材料",
}


@dataclass
class BusinessRef:
    """一条业务数据引用（会包装成伪 KnowledgeHit 参与统一编号）。"""

    source: str
    excerpt: str


@dataclass
class ToolOutcome:
    """单次工具执行结果。"""

    name: str
    ok: bool
    data: str = ""
    error: str | None = None
    latency_ms: int = 0
    args: dict[str, Any] = field(default_factory=dict)
    refs: list[BusinessRef] = field(default_factory=list)
    apps: list[dict[str, Any]] = field(default_factory=list)
    policy_hits: list[KnowledgeHit] = field(default_factory=list)


# ---------------------------------------------------------------- 对外入口


def execute_tool(
    name: str,
    args: dict[str, Any],
    db: Session,
    user: User,
    *,
    timeout: float,
) -> ToolOutcome:
    """执行单个工具，超时/异常一律降级为失败结果，不向上抛。"""
    handler = _HANDLERS.get(name)
    if handler is None:
        logger.warning("assistant.tool 未知工具 name=%s args=%s", name, _safe_args(args))
        return ToolOutcome(name=name, ok=False, error="未知工具", args=args)

    safe_args = _safe_args(args)
    logger.info(
        "assistant.tool 开始 name=%s role=%s args=%s timeout=%.1fs",
        name,
        getattr(getattr(user, "role", None), "value", "unknown"),
        safe_args,
        timeout,
    )

    start = time.perf_counter()
    executor = ThreadPoolExecutor(max_workers=1)
    try:
        future = executor.submit(handler, db, user, args)
        data, refs, apps, policy_hits = _unpack(future.result(timeout=max(0.1, timeout)))
        latency = int((time.perf_counter() - start) * 1000)
        rendered = _trim(data)
        logger.info(
            "assistant.tool 完成 name=%s latency_ms=%d chars=%d refs=%d apps=%d hits=%d",
            name,
            latency,
            len(rendered),
            len(refs),
            len(apps),
            len(policy_hits),
        )
        return ToolOutcome(
            name=name,
            ok=True,
            data=rendered,
            latency_ms=latency,
            args=safe_args,
            refs=refs,
            apps=apps,
            policy_hits=policy_hits,
        )
    except FutureTimeout:
        latency = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "assistant.tool 超时 name=%s timeout=%.1fs latency_ms=%d args=%s",
            name,
            timeout,
            latency,
            safe_args,
        )
        return ToolOutcome(
            name=name,
            ok=False,
            error="查询超时",
            latency_ms=latency,
            args=safe_args,
        )
    except Exception as exc:  # noqa: BLE001 — 工具异常不得中断整轮问答
        latency = int((time.perf_counter() - start) * 1000)
        logger.warning(
            "assistant.tool 失败 name=%s latency_ms=%d args=%s：%s",
            name,
            latency,
            safe_args,
            exc,
        )
        return ToolOutcome(
            name=name,
            ok=False,
            error="查询失败",
            latency_ms=latency,
            args=safe_args,
        )
    finally:
        executor.shutdown(wait=False)


# ---------------------------------------------------------------- 各工具实现


def _list_my_applications(
    db: Session, user: User, args: dict[str, Any]
) -> tuple[str, list[BusinessRef], list[dict[str, Any]]]:
    manager = _manager_name(user)
    status = _parse_status(args.get("status"))
    keyword = (args.get("keyword") or "").strip() or None

    rows, total = ApplicationRepository(db).list_by_manager(
        manager, status_filter=status, keyword=keyword, page=1, page_size=10
    )
    if not rows:
        filter_desc = f"（筛选条件：{STATUS_LABELS[status.value]}）" if status else ""
        return f"你名下没有符合条件的申请{filter_desc}。", [], []

    lines = [f"你名下共 {total} 笔申请，最近 {len(rows)} 笔如下："]
    refs: list[BusinessRef] = []
    apps: list[dict[str, Any]] = []
    for row in rows:
        line = _format_app_line(row)
        lines.append(line)
        refs.append(BusinessRef(source=f"申请 {row.app_no}", excerpt=line))
        apps.append({"id": row.id, "app_no": row.app_no})
    return "\n".join(lines), refs, apps


def _list_review_queue(
    db: Session, user: User, args: dict[str, Any]
) -> tuple[str, list[BusinessRef], list[dict[str, Any]]]:
    """风控复核队列：所有处于待风控复核状态的申请，不限客户经理。"""
    review_repo = ReviewRepository(db)
    rows = review_repo.list_risk_queue()
    returned_ids = review_repo.risk_returned_app_ids()

    if not rows:
        return "当前待风控复核队列为空，没有需要复核的申请。", [], []

    lines = [f"当前待风控复核共 {len(rows)} 笔申请："]
    refs: list[BusinessRef] = []
    apps: list[dict[str, Any]] = []
    for row in rows[:12]:
        line = _format_app_line(row)
        if row.id in returned_ids:
            line += "（补件已补齐）"
        lines.append(line)
        refs.append(BusinessRef(source=f"申请 {row.app_no}", excerpt=line))
        apps.append({"id": row.id, "app_no": row.app_no})
    return "\n".join(lines), refs, apps


# 客户经理待办状态（按处理优先级排序）
_TODO_STATUSES: tuple[ApplicationStatus, ...] = (
    ApplicationStatus.SUPPLEMENT,
    ApplicationStatus.MANUAL,
    ApplicationStatus.PRECHECK,
    ApplicationStatus.CHECK,
)


def _list_my_todos(
    db: Session, user: User, args: dict[str, Any]
) -> tuple[str, list[BusinessRef], list[dict[str, Any]]]:
    """主动汇总本人名下待办：先给分组计数，再按优先级列出待处理申请。"""
    manager = _manager_name(user)
    repo = ApplicationRepository(db)

    counts: list[str] = []
    rows_all: list[Application] = []
    for status in _TODO_STATUSES:
        rows, total = repo.list_by_manager(
            manager, status_filter=status, page=1, page_size=3
        )
        if not total:
            continue
        counts.append(f"{STATUS_LABELS[status.value]} {total} 笔")
        rows_all.extend(rows)

    if not counts:
        return "你名下暂无待办申请，当前没有需要你处理的申请。", [], []

    lines = ["你名下当前待办：" + "、".join(counts), "优先处理："]
    refs: list[BusinessRef] = []
    apps: list[dict[str, Any]] = []
    for row in rows_all[:8]:
        line = _format_app_line(row)
        lines.append(line)
        refs.append(BusinessRef(source=f"申请 {row.app_no}", excerpt=line))
        apps.append({"id": row.id, "app_no": row.app_no})
    if len(rows_all) > 8:
        lines.append(f"……另有 {len(rows_all) - 8} 笔待办，请在申请列表查看")
    return "\n".join(lines), refs, apps


def _get_application_detail(
    db: Session, user: User, args: dict[str, Any]
) -> tuple[str, list[BusinessRef], list[dict[str, Any]]]:
    app = _get_owned_app(db, user, args.get("app_id"))
    if app is None:
        return _NOT_FOUND_MSG, [], []

    materials = MaterialRepository(db).list_by_app(app.id)
    counts: Counter[str] = Counter()
    for m in materials:
        counts[_category_label(m.category)] += 1

    lines = [
        f"申请编号：{app.app_no}",
        f"企业名称：{app.company_name}",
        f"统一社会信用代码：{mask_credit_code(str(app.credit_code or '')) or '—'}",
        f"产品：{app.product}",
        f"申请金额：{_fmt_amount(app.amount)} 万元",
        f"当前状态：{STATUS_LABELS.get(_status_value(app.status), str(app.status))}",
        f"客户经理：{app.manager_name or '—'}",
    ]
    if app.supplement_note:
        source = {"manual": "人工复核退回", "risk": "风控退回"}.get(
            app.supplement_source or "", "退回"
        )
        lines.append(f"补件来源：{source}；补件说明：{app.supplement_note}")

    if materials:
        summary = "、".join(f"{label} {count} 份" for label, count in counts.items())
        lines.append(f"材料清单：共 {len(materials)} 个文件；{summary}")
        for m in materials[:8]:
            lines.append(
                f"- {_category_label(m.category)}：{m.file_name}（状态：{_material_status(m.status)}）"
            )
        if len(materials) > 8:
            lines.append(f"- ……另有 {len(materials) - 8} 个文件，请在详情页查看")
    else:
        lines.append("材料清单：暂无上传材料")

    text = "\n".join(lines)
    ref = BusinessRef(source=f"申请 {app.app_no}", excerpt=text)
    return text, [ref], [{"id": app.id, "app_no": app.app_no}]


def _get_precheck_summary(
    db: Session, user: User, args: dict[str, Any]
) -> tuple[str, list[BusinessRef], list[dict[str, Any]]]:
    app = _get_owned_app(db, user, args.get("app_id"))
    if app is None:
        return _NOT_FOUND_MSG, [], []

    report = ReportRepository(db).get_latest_by_app(app.id)
    if report is None:
        text = (
            f"申请 {app.app_no}（{app.company_name}）当前状态为"
            f"{STATUS_LABELS.get(_status_value(app.status), str(app.status))}，尚未生成 AI 预审报告。"
        )
        return text, [BusinessRef(source=f"申请 {app.app_no}", excerpt=text)], [
            {"id": app.id, "app_no": app.app_no}
        ]

    # 与申请列表「AI 摘要」共用同一份落库快照与同一个构造函数
    view = build_precheck_summary_view(report)
    text = render_precheck_summary_text(
        view, app_no=app.app_no, company_name=app.company_name
    )
    ref = BusinessRef(source=f"预审报告（申请 {app.app_no}）", excerpt=text)
    return text, [ref], [{"id": app.id, "app_no": app.app_no}]


def _list_products(
    db: Session, user: User, args: dict[str, Any]
) -> tuple[str, list[BusinessRef], list[dict[str, Any]]]:
    configs = list_rule_configs()
    if not configs:
        return "暂未读取到产品准入配置，请联系风控运营团队。", [], []

    lines = ["当前在售信贷产品："]
    refs: list[BusinessRef] = []
    for config in configs:
        product = str(config.get("product") or "")
        code = str(config.get("product_code") or "")
        feature = _PRODUCT_FEATURES.get(product, "")
        line = f"{product}（{code}）：{feature}".rstrip("：")
        lines.append(line)
        refs.append(BusinessRef(source=f"产品配置 {product}", excerpt=line))
    return "\n".join(lines), refs, []


def _preview_eligibility(
    db: Session, user: User, args: dict[str, Any]
) -> tuple[str, list[BusinessRef], list[dict[str, Any]]]:
    product = _resolve_product(args.get("product"))
    if product is None:
        return (
            "请说明要评估的产品：普惠小微经营贷 / 小微快贷 / 经营性抵押贷 / 科技e贷。",
            [],
            [],
        )
    config = load_rule_config(product)
    if not config:
        return f"未找到产品「{product}」的准入规则配置。", [], []

    app_id = args.get("app_id")
    if app_id not in (None, ""):
        app = _get_owned_app(db, user, app_id)
        if app is None:
            return _NOT_FOUND_MSG, [], []
        materials = MaterialRepository(db).list_by_app(app.id)
        consistency = check_consistency(app, materials)
        fields = build_rule_fields(app, materials, consistency)
        source = f"申请 {app.app_no} 准入预演（{product}）"
        apps = [{"id": app.id, "app_no": app.app_no}]
    else:
        profile = str(args.get("profile") or args.get("query") or "").strip()
        if not profile:
            return (
                "准入预演需要企业概况：请提供年营收、成立年限、资产负债率、申请金额等信息，"
                "或打开一笔已上传材料的申请再问我。",
                [],
                [],
            )
        fields = _profile_to_fields(profile)
        if not fields:
            return (
                "没能从描述里识别出可用指标，请补充年营收、成立年限、资产负债率、申请金额等。",
                [],
                [],
            )
        source = f"企业概况准入预演（{product}）"
        apps = []

    result = evaluate_rules(config, fields)
    text = _render_preview(source, result)
    return text, [BusinessRef(source=source, excerpt=text)], apps


def _get_required_materials(
    db: Session, user: User, args: dict[str, Any]
) -> tuple[str, list[BusinessRef], list[dict[str, Any]]]:
    product = _resolve_product(args.get("product"))
    if product is None:
        return (
            "请说明要查询哪个产品的材料清单：普惠小微经营贷 / 小微快贷 / 经营性抵押贷 / 科技e贷。",
            [],
            [],
        )

    hints: dict[str, str] = {}
    try:
        hints = retrieve_material_hints(
            {
                category.value: f"{product} {CATEGORY_LABELS[category]} 审核要点 要求"
                for category in CORE_REQUIRED_CATEGORIES
            }
        )
    except Exception as exc:  # noqa: BLE001 — 知识库不可用时用静态要点兜底
        logger.warning("assistant.materials 知识库检索失败：%s", exc)

    lines = [f"{product} 申请需要准备以下材料："]
    for category in CORE_REQUIRED_CATEGORIES:
        label = CATEGORY_LABELS[category]
        tip = _compact(hints.get(category.value) or _CATEGORY_TIPS.get(category, ""), 90)
        lines.append(f"- {label}（至少 1 份）：{tip}")

    for category, min_count, desc in extra_required_categories(product):
        label = CATEGORY_LABELS.get(category, str(category))
        lines.append(f"- {label}（至少 {min_count} 份）：{desc or '按规则要求提供'}")

    text = "\n".join(lines)
    return text, [BusinessRef(source=f"材料清单 {product}", excerpt=text)], []


def _search_policy(
    db: Session, user: User, args: dict[str, Any]
) -> tuple[str, list[BusinessRef], list[dict[str, Any]], list[KnowledgeHit]]:
    query = str(args.get("query") or "").strip()
    if not query:
        return "请说明要查询的政策问题。", [], [], []

    product = _resolve_product(args.get("product"))
    category = _resolve_category(args.get("category"))
    product_where = {"product": product} if product else None
    category_where = {"category": category} if category else None

    plans = [
        RetrievalPlan(KB_POLICY, top_k=3, where=product_where, keyword_hint=product or ""),
        RetrievalPlan(KB_RULE_CONFIG, top_k=2, where=product_where),
        RetrievalPlan(
            KB_MATERIAL_REVIEW, top_k=2, where=category_where, keyword_hint=category or ""
        ),
    ]
    hits, _used, _fallback = retrieve_policy_hits("general", query, plans, top_k=4)
    if not hits:
        return "知识库中暂未检索到相关政策原文。", [], [], []

    lines = [f"检索到 {len(hits)} 条政策依据："]
    for index, hit in enumerate(hits, 1):
        source = str((hit.metadata or {}).get("source") or "")
        lines.append(f"[{index}] {source}：{_compact(hit.text, 120)}")
    return "\n".join(lines), [], [], hits


_HANDLERS = {
    "list_my_applications": _list_my_applications,
    "get_application_detail": _get_application_detail,
    "get_precheck_summary": _get_precheck_summary,
    "list_products": _list_products,
    "preview_eligibility": _preview_eligibility,
    "get_required_materials": _get_required_materials,
    "search_policy": _search_policy,
    "list_my_todos": _list_my_todos,
    "list_review_queue": _list_review_queue,
}


# ---------------------------------------------------------------- 准入预演


_APPLY_AMOUNT_RE = re.compile(
    r"(?:申请金额|申请额度|贷款金额|贷款额度|额度|申请)[^\d]{0,8}([\d.]+)\s*万"
)
_REVENUE_RE = re.compile(r"(?:年营收|年营业收入|营业收入|营收|年收入|收入)[^\d]{0,8}([\d.]+)\s*万")
_NET_ASSET_RE = re.compile(r"(?:净资产|所有者权益)[^\d]{0,8}([\d.]+)\s*万")
_NET_PROFIT_RE = re.compile(r"(?:净利润|利润)[^\d]{0,8}(-?[\d.]+)\s*万")
_DEBT_RATIO_RE = re.compile(r"(?:资产负债率|负债率)[^\d]{0,4}([\d.]+)\s*%")
_COLLATERAL_RE = re.compile(r"(?:抵押物?评估价值|评估价值|评估值)[^\d]{0,8}([\d.]+)\s*万")
_YEARS_RE = re.compile(r"(?:成立|经营)[^\d]{0,6}([\d.]+)\s*年")
_INFLOW_RE = re.compile(r"(?:流水贷方合计|贷方合计|进账合计|流水合计)[^\d]{0,8}([\d.]+)\s*万")
_IP_RE = re.compile(r"(\d+)\s*(?:项|个)?\s*(?:发明专利|软件著作权|实用新型|知识产权|专利)")
_CREDIT_CODE_RE = re.compile(r"(?<![0-9A-Z])[0-9A-Z]{18}(?![0-9A-Z])")

_REGISTRATION_STATUSES: tuple[tuple[str, str], ...] = (
    ("吊销", "吊销"),
    ("注销", "注销"),
    ("迁出", "迁出"),
    ("存续", "存续"),
    ("在营", "在营"),
    ("开业", "开业"),
)


def _profile_to_fields(text: str) -> dict[str, RuleField]:
    """把企业概况自然语言转成规则字段；仅填能可靠识别的项，其余留给 uncertain。"""
    fields: dict[str, RuleField] = {}

    amount = _first_float(_APPLY_AMOUNT_RE, text)
    if amount is not None:
        fields["apply_amount"] = RuleField(amount, "企业概况", f"{amount:,.2f} 万元")

    revenue = _first_float(_REVENUE_RE, text)
    if revenue:
        fields["annual_revenue"] = RuleField(revenue, "企业概况", f"{revenue:,.2f} 万元")

    net_asset = _first_float(_NET_ASSET_RE, text)
    if net_asset:
        fields["net_asset"] = RuleField(net_asset, "企业概况", f"{net_asset:,.2f} 万元")

    if amount is not None and revenue:
        ratio = round(amount / revenue, 4)
        fields["loan_to_revenue"] = RuleField(ratio, "企业概况", f"{ratio:.2%}")
    if amount is not None and net_asset:
        ratio = round(amount / net_asset, 4)
        fields["loan_to_net_asset"] = RuleField(ratio, "企业概况", f"{ratio:.2%}")

    debt_ratio = _first_float(_DEBT_RATIO_RE, text)
    if debt_ratio is not None:
        value = round(debt_ratio / 100, 4)
        fields["debt_ratio"] = RuleField(value, "企业概况", f"{debt_ratio:.1f}%")

    profit = _first_float(_NET_PROFIT_RE, text)
    if profit is not None:
        fields["net_profit"] = RuleField(profit, "企业概况", f"{profit:,.2f} 万元")
        fields["profit_or_cashflow_positive"] = RuleField(
            profit > 0, "企业概况", "是" if profit > 0 else "否"
        )

    years = _first_float(_YEARS_RE, text)
    if years is not None:
        months = int(years * 12)
        fields["established_months"] = RuleField(months, "企业概况", f"{months} 个月")

    for keyword, status in _REGISTRATION_STATUSES:
        if keyword in text:
            fields["registration_status"] = RuleField(status, "企业概况", status)
            break

    code = _CREDIT_CODE_RE.search(text)
    if code:
        valid = _credit_code_valid(code.group(0))
        fields["credit_code_format"] = RuleField(
            "valid" if valid else "invalid",
            "企业概况",
            "有效" if valid else "无效",
        )

    if "无欠税" in text or "未欠税" in text:
        fields["has_major_tax_debt"] = RuleField(False, "企业概况", "无")
    elif "欠税" in text:
        fields["has_major_tax_debt"] = RuleField(True, "企业概况", "有")

    collateral = _first_float(_COLLATERAL_RE, text)
    if collateral:
        fields["collateral_value"] = RuleField(collateral, "企业概况", f"{collateral:,.2f} 万元")
        if amount is not None:
            ratio = round(amount / collateral, 4)
            fields["loan_to_collateral"] = RuleField(ratio, "企业概况", f"{ratio:.2%}")
    if "抵押" in text:
        fields["has_collateral_doc"] = RuleField(True, "企业概况", "已描述抵押物")

    inflow = _first_float(_INFLOW_RE, text)
    if inflow and revenue:
        ratio = round(inflow / revenue, 4)
        fields["annual_inflow_ratio"] = RuleField(ratio, "企业概况", f"{ratio:.2%}")
        fields["inflow_to_revenue"] = RuleField(ratio, "企业概况", f"{ratio:.2%}")

    if "高新技术" in text or "专精特新" in text:
        fields["has_tech_cert"] = RuleField(True, "企业概况", "具备")
    if "研发费用加计" in text:
        fields["has_rd_deduction"] = RuleField(True, "企业概况", "具备")

    ip_match = _IP_RE.search(text)
    if ip_match:
        fields["ip_count"] = RuleField(int(ip_match.group(1)), "企业概况", f"{ip_match.group(1)} 项")

    return fields


def _render_preview(source: str, result: Any) -> str:
    lines = [
        f"{source}：",
        f"预演评分 {float(result.score or 0):.0f} 分（等级 {result.level or '—'}）",
        f"规则预演：通过 {result.pass_count}/{result.total_count}；"
        f"不符合 {result.hard_fail_count + result.soft_fail_count} 项，"
        f"存疑 {result.uncertain_count} 项",
    ]
    non_pass = []
    uncertain_names: list[str] = []
    for item in result.rules:
        outcome = getattr(item.result, "value", item.result)
        if outcome == "pass":
            continue
        label = "不符合" if outcome == "fail" else "存疑"
        if outcome == "uncertain":
            uncertain_names.append(item.rule_name)
        non_pass.append(
            f"- [{label}] {item.rule_id} {item.rule_name}："
            f"预期 {item.expected or '—'}，实际 {item.actual or '缺失'}"
        )
    lines.extend(non_pass[:6])
    if len(non_pass) > 6:
        lines.append(f"- ……另有 {len(non_pass) - 6} 项")
    if not non_pass:
        lines.append("- 规则预演全部通过")
    if uncertain_names:
        lines.append(
            f"说明：{'、'.join(uncertain_names[:5])} 等 {len(uncertain_names)} 项因信息缺失标为存疑，"
            "需补齐材料后由正式预审判定。"
        )
    lines.append("以上为规则引擎预演结果，最终以正式 AI 预审为准。")
    return "\n".join(lines)


def _first_float(pattern: re.Pattern[str], text: str) -> float | None:
    match = pattern.search(text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except ValueError:
        return None


# ---------------------------------------------------------------- 内部工具


def _unpack(
    result: tuple[Any, ...]
) -> tuple[str, list[BusinessRef], list[dict[str, Any]], list[KnowledgeHit]]:
    """兼容 3 元 / 4 元返回（4 元为带知识库命中的工具）。"""
    if len(result) == 4:
        data, refs, apps, policy_hits = result
        return data, refs, apps, policy_hits
    data, refs, apps = result
    return data, refs, apps, []


def _resolve_product(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    if text in _PRODUCT_FEATURES:
        return text
    for name, aliases in PRODUCT_ALIASES.items():
        if name in text or any(alias in text for alias in aliases):
            return name
    return None


def _resolve_category(value: Any) -> str | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return MaterialCategory(text).value
    except ValueError:
        pass
    for category, label in CATEGORY_LABELS.items():
        if text == label or text in label:
            return category.value
    return None


def _manager_name(user: User) -> str:
    return (user.full_name or user.username or "").strip()


def _get_owned_app(db: Session, user: User, app_id: Any) -> Application | None:
    """按主键查询并校验归属。

    客户经理：仅能查看本人名下申请（manager_name 匹配）。
    风控复核员：可查看任意申请（风控复核不限制客户经理归属）。
    """
    try:
        app_id_int = int(app_id)
    except (TypeError, ValueError):
        return None
    app = ApplicationRepository(db).get_by_id(app_id_int)
    if app is None:
        return None
    if user.role != UserRole.RISK and app.manager_name != _manager_name(user):
        return None
    return app


def _parse_status(value: Any) -> ApplicationStatus | None:
    if not value:
        return None
    text = str(value).strip()
    code = _STATUS_ALIASES.get(text)
    if code is None:
        return None
    try:
        return ApplicationStatus(code)
    except ValueError:
        return None


def _status_value(status: Any) -> str:
    return status.value if isinstance(status, ApplicationStatus) else str(status)


def _material_status(status: Any) -> str:
    value = status.value if hasattr(status, "value") else str(status)
    return {"ok": "已识别", "low": "低置信", "pending": "待识别", "none": "无文件"}.get(
        str(value), str(value)
    )


def _category_label(code: Any) -> str:
    try:
        return CATEGORY_LABELS.get(code, str(code))  # type: ignore[arg-type]
    except Exception:  # noqa: BLE001
        return str(code)


def _format_app_line(row: Application) -> str:
    line = (
        f"{row.app_no} | {row.company_name} | {row.product} | "
        f"{_fmt_amount(row.amount)} 万元 | "
        f"{STATUS_LABELS.get(_status_value(row.status), str(row.status))}"
    )
    if row.supplement_note:
        line += f" | 补件说明：{row.supplement_note}"
    updated = getattr(row, "updated_at", None)
    if updated is not None:
        line += f" | 更新于 {updated:%Y-%m-%d %H:%M}"
    return line


def _fmt_amount(amount: Decimal | float | None) -> str:
    if amount is None:
        return "—"
    value = float(amount)
    return str(int(value)) if value.is_integer() else f"{value:.2f}"


def _compact(text: str, max_chars: int) -> str:
    compact = re.sub(r"\s+", " ", text or "").strip()
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "…"


def _trim(text: str, max_chars: int = MAX_TOOL_RESULT_CHARS) -> str:
    compact = "\n".join(line.strip() for line in text.splitlines() if line.strip())
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "…"


def _safe_args(args: dict[str, Any]) -> dict[str, Any]:
    """只保留可安全写入日志/响应的参数摘要。"""
    safe: dict[str, Any] = {}
    for key in ("app_id", "status", "product", "category"):
        if args.get(key) not in (None, ""):
            safe[key] = args[key]
    for key in ("keyword", "query", "profile"):
        value = args.get(key)
        if value:
            safe[key] = _compact(str(value), 60)
    return safe
