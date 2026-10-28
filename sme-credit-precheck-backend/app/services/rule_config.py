"""准入规则文件读取。

规则文件位于项目根目录 `rules/` 下，每个产品一个 YAML（rule_<产品>.yaml），
通过文件内的 `product` 字段与申请产品匹配。本模块只负责读取与解析，
规则判定逻辑由 rule_engine / analyzer 使用。
"""

import logging
from pathlib import Path

import yaml

from app.schemas.ai_classification import MaterialCategory

logger = logging.getLogger(__name__)

# 项目根目录下的规则目录
RULES_DIR = Path(__file__).resolve().parents[2] / "rules"

# 路径 + 修改时间 → 已解析配置，避免每次预审重复读取文件
_CONFIG_CACHE: dict[tuple[str, float], dict] = {}


def _load_yaml(path: Path) -> dict:
    """读取单个 YAML 文件，按「路径 + 修改时间」缓存。"""
    key = (str(path), path.stat().st_mtime)
    cached = _CONFIG_CACHE.get(key)
    if cached is not None:
        return cached
    with path.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    _CONFIG_CACHE[key] = data
    return data


def load_rule_config(product: str) -> dict | None:
    """按产品名加载准入规则配置，找不到对应文件时返回 None。"""
    if not product:
        return None
    if not RULES_DIR.exists():
        logger.warning("规则目录不存在：%s", RULES_DIR)
        return None
    for path in sorted(RULES_DIR.glob("rule_*.yaml")):
        try:
            config = _load_yaml(path)
        except (OSError, yaml.YAMLError) as exc:
            logger.warning("读取规则文件失败 %s：%s", path.name, exc)
            continue
        if config.get("product") == product:
            return config
    logger.warning("未找到产品「%s」对应的规则文件", product)
    return None


def extra_required_categories(product: str) -> list[tuple[MaterialCategory, int, str]]:
    """读取产品专属的额外必交材料。

    返回 [(类别, 最少份数, 说明)]；五大基础类别由代码固定为公共必交材料，
    不在规则文件中重复声明。`optional: true` 或 `min_count: 0` 的类别跳过。
    """
    config = load_rule_config(product)
    if not config:
        return []

    result: list[tuple[MaterialCategory, int, str]] = []
    for item in config.get("required_categories") or []:
        if not isinstance(item, dict) or item.get("optional"):
            continue
        raw_category = item.get("category")
        try:
            category = MaterialCategory(str(raw_category))
        except ValueError:
            logger.warning(
                "规则文件 product=%s 含未知材料类别：%s", product, raw_category
            )
            continue
        min_count = int(item.get("min_count") or 1)
        if min_count <= 0:
            continue
        result.append((category, min_count, str(item.get("desc") or "")))
    return result
