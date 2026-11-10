"""意图识别 + 检索计划。

纯规则实现，不调用 LLM：通过关键词命中 + 产品/材料上下文推断用户意图，
再映射到一组 RetrievalPlan。不命中任何意图时返回 kind="out_of_scope"。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from app.schemas.ai_classification import CATEGORY_LABELS, MaterialCategory

# 四个知识库 collection 名（与 kb_retriever.py 对齐）
KB_POLICY = "kb_policy"
KB_MATERIAL_REVIEW = "kb_material_review"
KB_RULE_CONFIG = "kb_rule_config"
KB_CASES = "kb_cases"

# 产品代码 ↔ 中文名 ↔ 关键词别名（用于意图识别）
PRODUCT_ALIASES: dict[str, list[str]] = {
    "普惠小微经营贷": ["普惠", "经营贷", "AP", "普惠小微"],
    "小微快贷": ["小微快贷", "快贷", "AK"],
    "经营性抵押贷": ["抵押贷", "抵押", "AJ"],
    "科技e贷": ["科技贷", "科技e", "科技", "AE"],
}
PRODUCT_CODE_TO_NAME = {
    "AP": "普惠小微经营贷",
    "AK": "小微快贷",
    "AJ": "经营性抵押贷",
    "AE": "科技e贷",
}

# 类别中文名 → 编码（反向）。CATEGORY_LABELS: dict[MaterialCategory, str]
# MaterialCategory 继承 str，所以 key 本身就是字符串编码
CATEGORY_NAME_TO_CODE: dict[str, str] = {label: code for code, label in CATEGORY_LABELS.items()}

# 规则编号正则：AP-H02 / AK-S05
RULE_ID_RE = re.compile(r"\b[A-Z]{2}-[HS]\d{2}\b")


# ---------------------------------------------------------------- 意图定义


@dataclass
class RetrievalPlan:
    """单条检索计划。"""

    collection: str
    top_k: int = 3
    where: dict[str, Any] | None = None
    keyword_hint: str = ""  # 兜底用：如果向量检索没命中，用这个关键词做文本匹配


@dataclass
class Intent:
    """识别结果。"""

    kind: str                              # product_admission / material_review / rule_explain / case_ref / operation_guide / general / out_of_scope
    confidence: float                      # 0~1
    keyword_used: list[str] = field(default_factory=list)
    plans: list[RetrievalPlan] = field(default_factory=list)
    product_hint: str | None = None        # 识别出的产品中文名（有则加 where）
    category_hint: str | None = None       # 识别出的材料类别编码（有则加 where）


# ---------------------------------------------------------------- 关键词表


_KEYWORDS: dict[str, list[str]] = {
    "product_admission": [
        "准入", "准入条件", "准入要求", "成立年限", "成立时间", "营业执照",
        "硬性门槛", "硬规则", "强规则", "不能做", "可以做什么产品", "能做什么产品",
        "申请条件", "申请要求",
    ],
    "material_review": [
        "流水", "银行流水", "财务报表", "征信授权", "纳税申报", "营业执照",
        "审核要点", "审核标准", "需要哪些材料", "需要什么材料", "材料清单",
        "材料要求", "完整性", "覆盖几个月", "字段", "要哪些字段",
    ],
    "rule_explain": [
        "不通过会怎么样", "不通过", "规则", "硬规则", "弱规则", "评分",
        "等级", "直接拒绝", "条件通过", "解释一下", "什么意思",
    ],
    "case_ref": [
        "之前", "有没有类似", "历史案例", "案例", "常见问题", "FAQ",
        "有没有先例", "类似情况",
    ],
    "operation_guide": [
        "怎么办", "怎么处理", "如何", "操作", "流程", "补件", "驳回",
        "退回", "通过", "审批", "申请流程",
    ],
}

# 业务领域词表：只要命中任意一个，就判定为「信贷政策相关问题」。
# 采用「白名单」而非黑名单：宁可放行到检索环节（检索不到会明确回答暂无内容），
# 也不要把正常业务咨询误判为无关问题。
_DOMAIN_TERMS: tuple[str, ...] = (
    # 业务主体
    "信贷", "贷款", "授信", "借款", "普惠", "小微", "企业", "商户", "个体",
    "客户", "经营",
    # 产品与要素
    "产品", "额度", "利率", "期限", "还款", "逾期", "负债", "担保", "抵押",
    "质押", "保证", "征信", "评级",
    # 政策与制度
    "政策", "制度", "规定", "办法", "指引", "合规", "监管",
    # 材料
    "材料", "清单", "流水", "对账", "报表", "财报", "资产负债表", "利润表",
    "纳税", "税务", "发票", "营业执照", "授权书", "验资", "工商", "登记",
    "合同", "订单", "开户", "账户", "回款", "进账",
    # 财务指标
    "营收", "营业收入", "收入", "利润", "净利润", "资产", "净资产", "成本",
    "成立年限", "注册资本", "法定代表人", "股东", "行业",
    # 流程与规则
    "准入", "预审", "复核", "风控", "审批", "申请", "补件", "退回", "驳回",
    "规则", "硬规则", "弱规则", "评分", "等级", "阈值", "条件",
    # 案例与问答
    "案例", "先例", "常见问题", "faq", "解释",
)


# ---------------------------------------------------------------- 识别主入口


def detect_intent(
    question: str,
    *,
    product_hint: str | None = None,
    category_hint: str | None = None,
) -> Intent:
    """识别意图并返回检索计划。

    :param question: 用户原始问题
    :param product_hint: 外部提示产品（如当前查看的申请所属产品）
    :param category_hint: 外部提示材料类别编码
    """
    text = question.strip()

    # 0. 先分类：判断是否属于信贷政策领域。无关问题直接返回，不检索、不调用 LLM。
    extracted_product = _extract_product(text) or product_hint
    extracted_category = _extract_category(text) or category_hint
    rule_ids = sorted(set(RULE_ID_RE.findall(text)))

    if not _is_in_scope(text, extracted_product, extracted_category, rule_ids):
        return Intent(kind="out_of_scope", confidence=0.9, keyword_used=[])

    # 2. 业务意图打分
    scores: dict[str, float] = {}
    used: dict[str, list[str]] = {}
    for kind, keywords in _KEYWORDS.items():
        matched = [kw for kw in keywords if kw in text]
        if matched:
            scores[kind] = 0.3 + 0.1 * len(matched)
            used[kind] = matched

    # 规则编号命中 → rule_explain 加分
    if rule_ids:
        scores["rule_explain"] = scores.get("rule_explain", 0) + 0.5
        used.setdefault("rule_explain", []).extend(rule_ids)

    # 产品/材料上下文 → product_admission / material_review 加分
    if extracted_product:
        scores["product_admission"] = scores.get("product_admission", 0) + 0.2
    if extracted_category:
        scores["material_review"] = scores.get("material_review", 0) + 0.2

    # 已通过领域分类但没命中细分关键词 → general，检索全部 collection
    if not scores:
        return Intent(
            kind="general",
            confidence=0.5,
            keyword_used=[],
            plans=_build_plans(
                "general",
                text,
                product=extracted_product,
                category=extracted_category,
                rule_ids=rule_ids,
            ),
            product_hint=extracted_product,
            category_hint=extracted_category,
        )

    # 3. 取最高分意图
    kind = max(scores, key=scores.get)  # type: ignore[arg-type]
    confidence = min(0.98, scores[kind])
    keyword_used = used.get(kind, [])

    # 4. 生成检索计划
    plans = _build_plans(
        kind,
        text,
        product=extracted_product,
        category=extracted_category,
        rule_ids=rule_ids,
    )

    return Intent(
        kind=kind,
        confidence=confidence,
        keyword_used=keyword_used,
        plans=plans,
        product_hint=extracted_product,
        category_hint=extracted_category,
    )


# ---------------------------------------------------------------- 辅助


def _is_in_scope(
    text: str,
    product: str | None,
    category: str | None,
    rule_ids: list[str],
) -> bool:
    """领域分类：命中产品/材料/规则编号/任一业务术语即视为相关。

    纯规则判定，不依赖 LLM，保证无关问题可以在毫秒级直接拒绝。
    """
    if product or category or rule_ids:
        return True
    lowered = text.lower()
    return any(term in text or term.lower() in lowered for term in _DOMAIN_TERMS)


def _extract_product(text: str) -> str | None:
    for code, aliases in PRODUCT_ALIASES.items():
        if any(alias in text for alias in aliases):
            return code
    # 中文产品名直接匹配
    for name in PRODUCT_ALIASES:
        if name in text:
            return name
    return None


def _extract_category(text: str) -> str | None:
    # 材料中文名 → 编码；优先长名字匹配避免"财务"之类的误命中
    for label, code in sorted(CATEGORY_NAME_TO_CODE.items(), key=lambda kv: len(kv[0]), reverse=True):
        if label in text:
            return code
    return None


def _build_plans(
    kind: str,
    question: str,
    *,
    product: str | None,
    category: str | None,
    rule_ids: list[str],
) -> list[RetrievalPlan]:
    """根据意图类型 + 上下文，生成检索计划列表。"""
    plans: list[RetrievalPlan] = []
    product_where = {"product": product} if product else None
    category_where = {"category": category} if category else None
    rule_where = {"rule_id": rule_ids[0]} if len(rule_ids) == 1 else None  # 多个时放弃精确过滤

    if kind == "product_admission":
        plans.append(RetrievalPlan(KB_POLICY, top_k=3, where=product_where, keyword_hint=product or ""))
        plans.append(RetrievalPlan(KB_RULE_CONFIG, top_k=2, where=product_where))
    elif kind == "material_review":
        plans.append(RetrievalPlan(KB_MATERIAL_REVIEW, top_k=3, where=category_where, keyword_hint=category or ""))
        if product:
            plans.append(RetrievalPlan(KB_POLICY, top_k=1, where=product_where))
    elif kind == "rule_explain":
        if rule_where:
            plans.append(RetrievalPlan(KB_RULE_CONFIG, top_k=2, where=rule_where, keyword_hint=rule_ids[0]))
        plans.append(RetrievalPlan(KB_RULE_CONFIG, top_k=3, where=product_where))
        plans.append(RetrievalPlan(KB_POLICY, top_k=2, where=product_where))
    elif kind == "case_ref":
        plans.append(RetrievalPlan(KB_CASES, top_k=4, where=product_where))
        plans.append(RetrievalPlan(KB_POLICY, top_k=2, where=product_where))
    elif kind == "operation_guide":
        plans.append(RetrievalPlan(KB_POLICY, top_k=2, where=product_where))
        plans.append(RetrievalPlan(KB_MATERIAL_REVIEW, top_k=2, where=category_where))
        plans.append(RetrievalPlan(KB_CASES, top_k=2))
    else:
        # 兜底：搜所有四个 collection
        for coll in (KB_POLICY, KB_MATERIAL_REVIEW, KB_RULE_CONFIG, KB_CASES):
            plans.append(RetrievalPlan(coll, top_k=1))

    return plans
