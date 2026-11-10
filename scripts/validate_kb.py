"""知识库内容校验脚本（阶段二）。

校验范围：
1. `index.yaml` 结构、版本号、条目与实际文件是否一致；
2. 所有 YAML 语法可解析；
3. 准入规则文件：必填字段、规则编号唯一性与格式、操作符、材料类别、
   评分参数自洽（基础分 + 弱规则分 × 条数 = 100）、等级阈值连续覆盖 0-100；
4. `评分配置.yaml` 与各产品规则文件中的 scoring 是否一致；
5. `结论口径.yaml`、`一致性校验规则.yaml` 结构完整性；
6. 文档口径与代码常量一致（六类材料编码、0.6 置信度阈值、五大公共必交材料）。

用法（项目根目录执行）：
    python scripts/validate_kb.py
    python scripts/validate_kb.py --strict      # WARNING 也视为失败
    python scripts/validate_kb.py --kb-dir knowledge_base

退出码：0=通过，1=存在错误（--strict 下含警告）。
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_KB_DIR = ROOT_DIR / "knowledge_base"
BACKEND_DIR = ROOT_DIR / "sme-credit-precheck-backend"

RULE_OPERATORS = {
    "eq",
    "neq",
    "gt",
    "gte",
    "lt",
    "lte",
    "in",
    "not_in",
    "contains",
}
RULE_KINDS = {"hard", "soft"}
FAIL_ACTIONS = {"reject", "manual"}
CONCLUSION_CODES = {"reject", "manual", "attention", "pass"}
CONCLUSION_KEYS = {
    "hard_rule_fail",
    "completeness_issue",
    "consistency_high_fail",
    "soft_rule_fail_count_ge_3",
    "else",
}
SEVERITIES = {"high", "medium", "low"}
CONSISTENCY_STATUS = {"pass", "fail", "uncertain"}

# 02 材料审核标准文档的类别识别（文件名关键字 → 类别编码）
CATEGORY_FILE_HINTS: dict[str, str] = {
    "营业执照": "business_license",
    "银行流水": "bank_statement",
    "财务报表": "financial_report",
    "纳税申报表": "tax_return",
    "征信授权书": "credit_auth",
    "其他材料": "other",
}


@dataclass
class Issue:
    level: str  # ERROR / WARNING
    file: str
    message: str

    def __str__(self) -> str:
        return f"[{self.level}] {self.file}: {self.message}"


@dataclass
class ValidationResult:
    errors: list[Issue] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    checked_files: int = 0

    def error(self, file: str, message: str) -> None:
        self.errors.append(Issue("ERROR", file, message))

    def warn(self, file: str, message: str) -> None:
        self.warnings.append(Issue("WARNING", file, message))


# ---------------------------------------------------------------- 代码常量


def load_code_constants() -> dict[str, Any]:
    """从后端代码导入产品枚举与材料类别常量（保持单一事实来源）。"""
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    from app.api.applications import PRODUCT_NO_PREFIX  # noqa: PLC0415
    from app.schemas.ai_classification import (  # noqa: PLC0415
        LOW_CONFIDENCE_THRESHOLD,
        MaterialCategory,
    )
    from app.schemas.ai_analysis import DEFAULT_REQUIRED_CATEGORIES  # noqa: PLC0415

    return {
        "products": PRODUCT_NO_PREFIX,
        "product_codes": set(PRODUCT_NO_PREFIX.values()),
        "categories": {c.value for c in MaterialCategory},
        "required_categories": [c.value for c in DEFAULT_REQUIRED_CATEGORIES],
        "low_confidence_threshold": LOW_CONFIDENCE_THRESHOLD,
    }


# ---------------------------------------------------------------- 通用工具


def load_yaml(path: Path, result: ValidationResult, display: str) -> Any:
    """读取 YAML，语法错误记入校验结果并返回 None。"""
    try:
        with path.open("r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except (OSError, yaml.YAMLError) as exc:
        result.error(display, f"YAML 解析失败：{exc}")
        return None


def semantic_rule_config(config: dict[str, Any]) -> dict[str, Any]:
    """去掉版本相关字段，用于比较知识库源与运行时文件是否语义一致。"""
    return {k: v for k, v in config.items() if k not in {"version", "updated_at"}}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


# ---------------------------------------------------------------- 索引校验


def check_index(kb_dir: Path, result: ValidationResult) -> None:
    index_path = kb_dir / "index.yaml"
    if not index_path.exists():
        result.error("index.yaml", "知识库缺少 index.yaml")
        return

    data = load_yaml(index_path, result, "index.yaml")
    if not isinstance(data, dict):
        return

    version = str(data.get("version") or "")
    if not re.fullmatch(r"v\d{4}-\d{2}-\d{2}", version):
        result.error("index.yaml", f"version 格式应为 vYYYY-MM-DD，当前为 {version!r}")

    updated_at = str(data.get("updated_at") or "")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", updated_at):
        result.error("index.yaml", f"updated_at 格式应为 YYYY-MM-DD，当前为 {updated_at!r}")

    sections = data.get("sections")
    if not isinstance(sections, list) or not sections:
        result.error("index.yaml", "sections 必须为非空列表")
        return

    listed: set[str] = set()
    for section in sections:
        if not isinstance(section, dict):
            result.error("index.yaml", "sections 条目必须是对象")
            continue
        name = str(section.get("name") or "")
        rel_dir = str(section.get("path") or "")
        items = section.get("items")
        if not name or not rel_dir:
            result.error("index.yaml", "section 缺少 name / path")
            continue
        if not (kb_dir / rel_dir).is_dir():
            result.error("index.yaml", f"section {name} 的目录不存在：{rel_dir}")
            continue
        if not isinstance(items, list) or not items:
            result.error("index.yaml", f"section {name} 的 items 必须为非空列表")
            continue
        for item in items:
            rel = Path(rel_dir) / str(item)
            listed.add(rel.as_posix())
            if not (kb_dir / rel).is_file():
                result.error("index.yaml", f"条目文件不存在：{rel.as_posix()}")

    # 实际文件与索引条目双向比对
    for path in sorted(kb_dir.rglob("*")):
        if not path.is_file():
            continue
        if path.name in {"index.yaml", "README.md"}:
            continue
        rel = path.relative_to(kb_dir).as_posix()
        if rel not in listed:
            result.warn("index.yaml", f"文件未登记到索引：{rel}")


# ---------------------------------------------------------------- 规则文件校验


def _validate_required_categories(
    config: dict[str, Any], ctx: dict[str, Any], result: ValidationResult, display: str
) -> None:
    items = config.get("required_categories")
    if items is None:
        return
    if not isinstance(items, list):
        result.error(display, "required_categories 必须为列表")
        return
    for index, item in enumerate(items, start=1):
        where = f"required_categories[{index}]"
        if not isinstance(item, dict):
            result.error(display, f"{where} 必须是对象")
            continue
        category = item.get("category")
        if category not in ctx["categories"]:
            result.error(display, f"{where}.category 非法：{category!r}")
        if "min_count" in item and not isinstance(item.get("min_count"), int):
            result.error(display, f"{where}.min_count 必须为整数")
        if not isinstance(item.get("desc"), str) or not item.get("desc"):
            result.error(display, f"{where}.desc 必须为非空字符串")


def _validate_rule_item(
    rule: Any,
    index: int,
    product_code: str,
    ctx: dict[str, Any],
    result: ValidationResult,
    display: str,
) -> str | None:
    where = f"rules[{index}]"
    if not isinstance(rule, dict):
        result.error(display, f"{where} 必须是对象")
        return None

    required = [
        "rule_id",
        "rule_name",
        "kind",
        "source",
        "field",
        "operator",
        "value",
        "detail_zh",
    ]
    missing = [key for key in required if key not in rule]
    if missing:
        result.error(display, f"{where} 缺少字段：{', '.join(missing)}")
        return None

    rule_id = str(rule["rule_id"])
    if not re.fullmatch(rf"{re.escape(product_code)}-[HS]\d{{2}}", rule_id):
        result.error(display, f"{where}.rule_id 格式非法（应为 {product_code}-H/S+两位数字）：{rule_id}")
    kind = rule["kind"]
    if kind not in RULE_KINDS:
        result.error(display, f"{where}.kind 非法：{kind!r}")
    elif rule_id and "-" in rule_id:
        expected = "hard" if "-H" in rule_id else "soft"
        if kind != expected:
            result.error(display, f"{where}.kind 与编号不一致：{rule_id} 应为 {expected}")

    sources = rule["source"] if isinstance(rule["source"], list) else [rule["source"]]
    valid_sources = ctx["categories"] | {"application"}
    for source in sources:
        if source not in valid_sources:
            result.error(display, f"{where}.source 含未知证据来源：{source!r}")

    operator = rule["operator"]
    if operator not in RULE_OPERATORS:
        result.error(display, f"{where}.operator 非法：{operator!r}")

    if not isinstance(rule["field"], str) or not rule["field"]:
        result.error(display, f"{where}.field 必须为非空字符串")
    if not isinstance(rule["detail_zh"], str) or not rule["detail_zh"]:
        result.error(display, f"{where}.detail_zh 必须为非空字符串")
    if rule["value"] is None:
        result.error(display, f"{where}.value 不能为空")

    if kind == "hard" and rule.get("fail_action") is not None:
        # fail_action 可省略（默认 reject），显式声明时必须合法
        if rule.get("fail_action") not in FAIL_ACTIONS:
            result.error(display, f"{where}.fail_action 必须为 reject/manual")
    elif kind == "soft" and rule.get("fail_action") is not None:
        result.error(display, f"{where} 为弱规则，不应设置 fail_action")

    return rule_id


def _validate_ranges(
    thresholds: Any, result: ValidationResult, display: str
) -> None:
    if not isinstance(thresholds, dict) or not thresholds:
        result.error(display, "scoring.level_thresholds 必须为非空对象")
        return

    ranges: list[tuple[float, float]] = []
    for label, value in thresholds.items():
        if not isinstance(value, list) or len(value) != 2:
            result.error(display, f"level_thresholds.{label} 必须是 [下界, 上界]")
            continue
        low, high = value
        if not (_is_number(low) and _is_number(high)):
            result.error(display, f"level_thresholds.{label} 必须为数字区间")
            continue
        if low > high:
            result.error(display, f"level_thresholds.{label} 下界大于上界")
        ranges.append((float(low), float(high)))

    ordered = sorted(ranges)
    if ordered and ordered[0][0] != 0:
        result.warn(display, "level_thresholds 未从 0 分开始，存在未覆盖分数段")
    if ordered and ordered[-1][1] != 100:
        result.warn(display, "level_thresholds 未覆盖到 100 分")
    for prev, curr in zip(ordered, ordered[1:]):
        if curr[0] > prev[1] + 1:
            result.error(display, f"等级阈值存在断档：{prev[1]} → {curr[0]}")
        elif curr[0] <= prev[1]:
            result.error(display, f"等级阈值存在重叠：{prev} 与 {curr}")


def check_rule_file(
    path: Path,
    product_code_map: dict[str, str],
    ctx: dict[str, Any],
    result: ValidationResult,
    seen_rule_ids: dict[str, str],
) -> dict[str, Any] | None:
    display = f"03_规则配置/准入规则/{path.name}"
    config = load_yaml(path, result, display)
    if not isinstance(config, dict):
        return None

    for key in ("version", "updated_at", "product", "product_code", "rules", "scoring", "conclusion_logic"):
        if key not in config:
            result.error(display, f"缺少顶层字段：{key}")
    if not config:
        return None

    product = str(config.get("product") or "")
    code = str(config.get("product_code") or "")
    if product not in product_code_map:
        result.error(display, f"product 与系统产品枚举不一致：{product!r}")
    elif code != product_code_map[product]:
        result.error(
            display,
            f"product_code 与 applications 前缀不一致：期望 {product_code_map[product]}，实际 {code}",
        )

    version = str(config.get("version") or "")
    if not re.fullmatch(r"v\d{4}-\d{2}-\d{2}", version):
        result.error(display, f"version 格式应为 vYYYY-MM-DD，当前为 {version!r}")

    _validate_required_categories(config, ctx, result, display)

    rules = config.get("rules")
    if not isinstance(rules, list) or not rules:
        result.error(display, "rules 必须为非空列表")
        rules = []

    hard_count = 0
    soft_count = 0
    for index, rule in enumerate(rules):
        rule_id = _validate_rule_item(rule, index, code, ctx, result, display)
        if rule_id:
            if rule_id in seen_rule_ids:
                result.error(display, f"rule_id 重复：{rule_id}（已出现在 {seen_rule_ids[rule_id]}）")
            else:
                seen_rule_ids[rule_id] = display
        if isinstance(rule, dict):
            if rule.get("kind") == "hard":
                hard_count += 1
            elif rule.get("kind") == "soft":
                soft_count += 1

    scoring = config.get("scoring")
    if not isinstance(scoring, dict):
        result.error(display, "scoring 必须为对象")
        return config

    base = scoring.get("base_score")
    soft_score = scoring.get("soft_rule_score")
    if not _is_number(base) or not _is_number(soft_score):
        result.error(display, "scoring.base_score / soft_rule_score 必须为数字")
    elif base + soft_score * soft_count != 100:
        result.error(
            display,
            f"评分不满 100：base_score({base}) + soft_rule_score({soft_score}) × "
            f"弱规则数({soft_count}) = {base + soft_score * soft_count}",
        )

    if not isinstance(scoring.get("hard_rules_reject"), bool):
        result.error(display, "scoring.hard_rules_reject 必须为布尔值")

    _validate_ranges(scoring.get("level_thresholds"), result, display)

    thresholds = scoring.get("level_thresholds") if isinstance(scoring.get("level_thresholds"), dict) else {}
    for key in ("level_label", "level_note"):
        mapping = scoring.get(key)
        if not isinstance(mapping, dict) or set(mapping) != set(thresholds):
            result.error(display, f"scoring.{key} 的键必须与 level_thresholds 完全一致")

    logic = config.get("conclusion_logic")
    if not isinstance(logic, dict):
        result.error(display, "conclusion_logic 必须为对象")
    else:
        missing = CONCLUSION_KEYS - set(logic)
        if missing:
            result.error(display, f"conclusion_logic 缺少键：{', '.join(sorted(missing))}")
        for key, value in logic.items():
            if key in CONCLUSION_KEYS and value not in CONCLUSION_CODES:
                result.error(display, f"conclusion_logic.{key} 非法结论：{value!r}")

    return config


def check_scoring_config(
    kb_dir: Path,
    rule_configs: list[dict[str, Any]],
    product_codes: set[str],
    result: ValidationResult,
) -> None:
    path = kb_dir / "03_规则配置" / "说明配置" / "评分配置.yaml"
    display = "03_规则配置/说明配置/评分配置.yaml"
    if not path.exists():
        result.error(display, "缺少评分配置.yaml")
        return

    data = load_yaml(path, result, display)
    if not isinstance(data, dict):
        return
    products = data.get("products")
    if not isinstance(products, dict):
        result.error(display, "products 必须为对象")
        return

    if set(products) != product_codes:
        result.error(
            display,
            f"products 键与产品代码不一致：期望 {sorted(product_codes)}，实际 {sorted(products)}",
        )

    by_code = {
        str(config.get("product_code")): config
        for config in rule_configs
        if isinstance(config, dict)
    }
    for code, item in products.items():
        if not isinstance(item, dict):
            result.error(display, f"products.{code} 必须为对象")
            continue
        rule_config = by_code.get(code)
        if not rule_config:
            continue
        scoring = rule_config.get("scoring") or {}
        for field_name in ("base_score", "soft_rule_score"):
            if item.get(field_name) != scoring.get(field_name):
                result.error(
                    display,
                    f"products.{code}.{field_name} 与规则文件不一致："
                    f"{item.get(field_name)!r} != {scoring.get(field_name)!r}",
                )
        soft_count = sum(
            1 for rule in (rule_config.get("rules") or []) if rule.get("kind") == "soft"
        )
        if item.get("soft_rule_count") != soft_count:
            result.error(
                display,
                f"products.{code}.soft_rule_count 与规则条数不一致："
                f"{item.get('soft_rule_count')!r} != {soft_count}",
            )
        if _is_number(item.get("base_score")) and _is_number(item.get("soft_rule_score")):
            full = item["base_score"] + item["soft_rule_score"] * soft_count
            if item.get("full_score") != full:
                result.error(
                    display,
                    f"products.{code}.full_score 与计算值不一致：{item.get('full_score')!r} != {full}",
                )


def check_conclusion_config(
    kb_dir: Path,
    rule_configs: list[dict[str, Any]],
    result: ValidationResult,
) -> None:
    path = kb_dir / "03_规则配置" / "说明配置" / "结论口径.yaml"
    display = "03_规则配置/说明配置/结论口径.yaml"
    if not path.exists():
        result.error(display, "缺少结论口径.yaml")
        return

    data = load_yaml(path, result, display)
    if not isinstance(data, dict):
        return

    conclusions = data.get("conclusions")
    if not isinstance(conclusions, list) or not conclusions:
        result.error(display, "conclusions 必须为非空列表")
    else:
        codes = {str(item.get("code")) for item in conclusions if isinstance(item, dict)}
        if codes != CONCLUSION_CODES:
            result.error(display, f"conclusions.code 必须为 {sorted(CONCLUSION_CODES)}，实际 {sorted(codes)}")
        priorities = [item.get("priority") for item in conclusions if isinstance(item, dict)]
        if sorted(p for p in priorities if _is_number(p)) != [1, 2, 3, 4]:
            result.error(display, f"conclusions.priority 必须为唯一 1-4，实际 {priorities}")

    logic = data.get("logic")
    if not isinstance(logic, list) or not logic:
        result.error(display, "logic 必须为非空列表")
    else:
        for index, item in enumerate(logic):
            if not isinstance(item, dict):
                result.error(display, f"logic[{index}] 必须是对象")
                continue
            if item.get("conclusion") not in CONCLUSION_CODES:
                result.error(display, f"logic[{index}].conclusion 非法：{item.get('conclusion')!r}")

    transition = data.get("status_transition")
    if not isinstance(transition, dict) or set(transition) != CONCLUSION_CODES:
        result.error(display, "status_transition 的键必须覆盖四类结论")

    supplement = data.get("supplement_source")
    if not isinstance(supplement, dict) or set(supplement) != {"manual", "risk"}:
        result.error(display, "supplement_source 必须包含 manual / risk 两类")

    # 与各规则文件的 conclusion_logic 对齐
    expected = {
        "hard_rule_fail": "reject",
        "completeness_issue": "manual",
        "consistency_high_fail": "attention",
        "soft_rule_fail_count_ge_3": "attention",
        "else": "pass",
    }
    for config in rule_configs:
        if not isinstance(config, dict):
            continue
        product = config.get("product")
        logic_config = config.get("conclusion_logic")
        if not isinstance(logic_config, dict):
            continue
        for key, value in expected.items():
            if logic_config.get(key) != value:
                result.error(
                    display,
                    f"产品 {product} 的 conclusion_logic.{key} 应为 {value}，"
                    f"实际 {logic_config.get(key)!r}（与结论口径.yaml 不一致）",
                )


def check_consistency_config(kb_dir: Path, ctx: dict[str, Any], result: ValidationResult) -> None:
    path = kb_dir / "03_规则配置" / "说明配置" / "一致性校验规则.yaml"
    display = "03_规则配置/说明配置/一致性校验规则.yaml"
    if not path.exists():
        result.error(display, "缺少一致性校验规则.yaml")
        return

    data = load_yaml(path, result, display)
    if not isinstance(data, dict):
        return

    status = data.get("status")
    if not isinstance(status, dict) or set(status) != CONSISTENCY_STATUS:
        result.error(display, "status 必须覆盖 pass / fail / uncertain")

    severity = data.get("severity")
    if not isinstance(severity, dict) or set(severity) != SEVERITIES:
        result.error(display, "severity 必须覆盖 high / medium / low")

    checks = data.get("checks")
    if not isinstance(checks, list) or not checks:
        result.error(display, "checks 必须为非空列表")
        return

    seen: set[str] = set()
    valid_sources = ctx["categories"] | {"application"}
    for index, item in enumerate(checks):
        if not isinstance(item, dict):
            result.error(display, f"checks[{index}] 必须是对象")
            continue
        check_id = str(item.get("check_id") or "")
        if not re.fullmatch(r"C\d+", check_id):
            result.error(display, f"checks[{index}].check_id 格式应为 C+数字：{check_id!r}")
        elif check_id in seen:
            result.error(display, f"check_id 重复：{check_id}")
        seen.add(check_id)
        if item.get("severity") not in SEVERITIES:
            result.error(display, f"checks[{index}].severity 非法：{item.get('severity')!r}")
        sources = item.get("sources")
        if not isinstance(sources, list) or not sources:
            result.error(display, f"checks[{index}].sources 必须为非空列表")
        else:
            for source in sources:
                if source not in valid_sources:
                    result.error(display, f"checks[{index}].sources 含未知来源：{source!r}")

    tolerance = data.get("tolerance")
    if not isinstance(tolerance, dict) or not _is_number(tolerance.get("amount")):
        result.error(display, "tolerance.amount 必须为数字")
    elif float(tolerance["amount"]) <= 0:
        result.error(display, "tolerance.amount 必须大于 0")


# ---------------------------------------------------------------- 文档口径校验


def check_docs(kb_dir: Path, ctx: dict[str, Any], result: ValidationResult) -> None:
    category_doc = kb_dir / "02_材料审核标准" / "材料分类标准.md"
    display = "02_材料审核标准/材料分类标准.md"
    if not category_doc.exists():
        result.error(display, "缺少材料分类标准.md")
    else:
        text = category_doc.read_text(encoding="utf-8")
        for category in sorted(ctx["categories"]):
            if category not in text:
                result.error(display, f"文档缺少材料类别编码：{category}")
        threshold = str(ctx["low_confidence_threshold"])
        if threshold not in text:
            result.error(display, f"文档缺少分类置信度阈值：{threshold}")

    completeness_doc = kb_dir / "02_材料审核标准" / "完整性要求.md"
    display = "02_材料审核标准/完整性要求.md"
    if not completeness_doc.exists():
        result.error(display, "缺少完整性要求.md")
    else:
        text = completeness_doc.read_text(encoding="utf-8")
        labels = {
            "business_license": "营业执照",
            "bank_statement": "银行流水",
            "financial_report": "财务报表",
            "tax_return": "纳税申报表",
            "credit_auth": "征信授权书",
        }
        for category in ctx["required_categories"]:
            label = labels.get(category, category)
            if label not in text:
                result.error(display, f"文档缺少公共必交材料：{label}")

    review_dir = kb_dir / "02_材料审核标准" / "各材料审核要点"
    for name in CATEGORY_FILE_HINTS:
        path = review_dir / f"{name}审核要点.md"
        if not path.exists():
            result.error("02_材料审核标准/各材料审核要点", f"缺少审核要点文档：{path.name}")


# ---------------------------------------------------------------- 主流程


def run_validation(kb_dir: Path) -> ValidationResult:
    result = ValidationResult()
    ctx = load_code_constants()

    if not kb_dir.is_dir():
        result.error(str(kb_dir), "知识库目录不存在")
        return result

    check_index(kb_dir, result)

    for path in sorted(kb_dir.rglob("*.yaml")):
        result.checked_files += 1
        try:
            with path.open("r", encoding="utf-8") as handle:
                yaml.safe_load(handle)
        except (OSError, yaml.YAMLError) as exc:
            result.error(path.relative_to(kb_dir).as_posix(), f"YAML 解析失败：{exc}")

    rule_configs: list[dict[str, Any]] = []
    seen_rule_ids: dict[str, str] = {}
    for path in sorted((kb_dir / "03_规则配置" / "准入规则").glob("rule_*.yaml")):
        config = check_rule_file(path, ctx["products"], ctx, result, seen_rule_ids)
        if isinstance(config, dict):
            rule_configs.append(config)

    check_scoring_config(kb_dir, rule_configs, ctx["product_codes"], result)
    check_conclusion_config(kb_dir, rule_configs, result)
    check_consistency_config(kb_dir, ctx, result)
    check_docs(kb_dir, ctx, result)

    return result


def print_result(result: ValidationResult) -> None:
    for issue in result.errors:
        print(issue)
    for issue in result.warnings:
        print(issue)
    print("-" * 60)
    print(
        f"校验完成：{result.checked_files} 个 YAML，"
        f"错误 {len(result.errors)} 个，警告 {len(result.warnings)} 个"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="校验信贷政策与材料审核知识库")
    parser.add_argument("--kb-dir", default=str(DEFAULT_KB_DIR), help="知识库根目录")
    parser.add_argument("--strict", action="store_true", help="将 WARNING 也视为失败")
    args = parser.parse_args(argv)

    try:
        result = run_validation(Path(args.kb_dir))
    except ImportError as exc:
        print(f"[ERROR] 无法导入后端代码常量：{exc}", file=sys.stderr)
        return 1

    print_result(result)
    if result.errors or (args.strict and result.warnings):
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
