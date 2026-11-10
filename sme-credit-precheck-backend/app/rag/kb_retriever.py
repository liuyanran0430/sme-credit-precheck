"""知识库 RAG 检索（阶段三）。

定位：**仅用于证据溯源、规则解释、字段抽取兜底**，不参与任何规则判定、
评分或结论生成。检索失败一律降级为空结果并输出 WARNING，绝不中断 AI 预审主流程。

Collection 规划（与 scripts/rebuild_vector_index.py 保持一致）：
    kb_policy           01_信贷政策      元数据：product / rule_id / kind
    kb_material_review  02_材料审核标准  元数据：category / check_item
    kb_rule_config      03_规则配置      元数据：product / rule_id / kind / version
    kb_cases            04_案例与FAQ     元数据：case_type / product

降级策略（对应设计方案 §6.4）：
- 索引为空 → 直接跳过，不触发 embedding；
- Embedding 不可用/失败 → 冷却一段时间内跳过检索，避免重复失败拖慢预审；
- 向量检索异常 → 仅 WARNING，返回空结果；
- 检索结果为空 → 上层继续使用 YAML 规则中的 detail_zh。
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from typing import Any, Sequence

from app.core import config
from app.rag.factory import get_vector_store

logger = logging.getLogger(__name__)

KB_POLICY = "kb_policy"
KB_MATERIAL_REVIEW = "kb_material_review"
KB_RULE_CONFIG = "kb_rule_config"
KB_CASES = "kb_cases"

_WHITESPACE_RE = re.compile(r"\s+")

# 检索降级标记：embedding 或向量库不可用后，冷却期内的检索直接跳过
_disabled_until: float = 0.0
_disabled_reason: str = ""
# 索引是否可用的正向缓存（为空时不缓存，重建索引后无需重启即可生效）
_index_ready: dict[str, bool] = {}
_index_warned: set[str] = set()


@dataclass
class KnowledgeHit:
    """命中的知识块。"""

    collection: str
    text: str
    score: float
    metadata: dict[str, Any] = field(default_factory=dict)


def _normalize_text(text: str, max_chars: int) -> str:
    """压缩空白并截断超长文本，避免报告字段过长。"""
    compact = _WHITESPACE_RE.sub(" ", text).strip()
    if len(compact) <= max_chars:
        return compact
    return compact[:max_chars].rstrip() + "…"


def _enabled() -> bool:
    """RAG 是否可用：开关打开且不在降级冷却期。"""
    if not config.KB_RAG_ENABLED:
        return False
    return time.monotonic() >= _disabled_until


def _disable(reason: str) -> None:
    """触发降级冷却，后续检索在冷却期内直接跳过。"""
    global _disabled_until, _disabled_reason
    cooldown = max(0, config.KB_RAG_COOLDOWN_SECONDS)
    _disabled_until = time.monotonic() + cooldown
    _disabled_reason = reason
    logger.warning(
        "知识库 RAG 检索降级：%s；%d 秒内跳过检索（不影响预审判定）",
        reason,
        cooldown,
    )


def _index_has_data(collection: str) -> bool:
    """索引是否已建好。为空时只告警一次，且不缓存空状态。"""
    if _index_ready.get(collection):
        return True
    try:
        stats = get_vector_store().get_collection_stats(collection)
        count = int(stats.get("count") or 0)
    except Exception as exc:  # noqa: BLE001 — 统计失败按空索引处理
        logger.warning("知识库索引检查失败（collection=%s）：%s", collection, exc)
        return False

    if count > 0:
        _index_ready[collection] = True
        return True

    if collection not in _index_warned:
        _index_warned.add(collection)
        logger.warning(
            "知识库索引为空（collection=%s），本次跳过 RAG 检索；"
            "请先执行 scripts/rebuild_vector_index.py 重建索引",
            collection,
        )
    return False


def _embed(texts: list[str]) -> list[list[float]] | None:
    """批量生成向量；失败时触发降级冷却并返回 None。"""
    try:
        from app.llm import get_embedding_client

        return get_embedding_client().embed(texts)
    except Exception as exc:  # noqa: BLE001 — embedding 故障不得中断主流程
        _disable(f"Embedding 调用失败：{exc}")
        return None


def _query(
    collection: str,
    vector: list[float],
    *,
    where: dict[str, Any] | None = None,
    top_k: int | None = None,
) -> list[KnowledgeHit]:
    """向量检索；异常时返回空列表。"""
    if not _enabled():
        return []
    try:
        results = get_vector_store().query(
            vector,
            top_k=top_k or config.KB_RAG_TOP_K,
            where=where,
            collection=collection,
        )
    except Exception as exc:  # noqa: BLE001 — 检索故障不得中断主流程
        _disable(f"向量检索失败（collection={collection}）：{exc}")
        return []

    return [
        KnowledgeHit(
            collection=collection,
            text=item.document.text,
            score=float(item.score),
            metadata=dict(item.document.metadata or {}),
        )
        for item in results
    ]


def search(
    collection: str,
    query_text: str,
    *,
    where: dict[str, Any] | None = None,
    top_k: int | None = None,
) -> list[KnowledgeHit]:
    """通用知识库检索入口（单条查询）。"""
    if not _enabled() or not query_text.strip():
        return []
    if not _index_has_data(collection):
        return []

    vectors = _embed([query_text])
    if not vectors:
        return []
    return _query(collection, vectors[0], where=where, top_k=top_k)


def _pick_by_rule(hits: Sequence[KnowledgeHit], rule_id: str) -> KnowledgeHit | None:
    """优先选择元数据 rule_id 命中该规则的块（支持逗号分隔的多规则块）。"""
    for hit in hits:
        ids = str(hit.metadata.get("rule_id") or "")
        if rule_id and rule_id in {item.strip() for item in ids.split(",")}:
            return hit
    return None


def retrieve_rule_basis(
    product: str,
    rules: Sequence[tuple[str, str]],
) -> dict[str, str]:
    """按规则逐条检索知识库政策依据。

    :param product: 产品中文名（与申请记录一致）
    :param rules: [(rule_id, rule_name), ...]
    :return: {rule_id: 依据原文}
    """
    if not _enabled() or not rules:
        return {}

    policy_ready = _index_has_data(KB_POLICY)
    config_ready = _index_has_data(KB_RULE_CONFIG)
    if not policy_ready and not config_ready:
        return {}

    prompts = [
        f"{product} 准入规则 {rule_id} {rule_name} 政策依据"
        for rule_id, rule_name in rules
    ]
    vectors = _embed(prompts)
    if not vectors:
        return {}

    basis: dict[str, str] = {}
    max_chars = config.KB_RAG_BASIS_MAX_CHARS
    for (rule_id, _rule_name), vector in zip(rules, vectors):
        if not _enabled():
            break

        hit: KnowledgeHit | None = None
        if policy_ready:
            hits = _query(
                KB_POLICY, vector, where={"product": product}, top_k=config.KB_RAG_TOP_K
            )
            hit = _pick_by_rule(hits, rule_id)
        if hit is None and config_ready:
            # 回退到规则配置块：按 rule_id 精确过滤，命中即该规则的机器可读定义
            hits = _query(KB_RULE_CONFIG, vector, where={"rule_id": rule_id}, top_k=1)
            hit = hits[0] if hits else None

        if hit is not None and hit.text.strip():
            basis[rule_id] = _normalize_text(hit.text, max_chars)

    return basis


def retrieve_material_hints(category_queries: dict[str, str]) -> dict[str, str]:
    """按材料类别检索审核要点，用于字段抽取失败时的兜底提示。

    :param category_queries: {category: 检索文本}
    :return: {category: 审核要点原文}
    """
    if not _enabled() or not category_queries:
        return {}
    if not _index_has_data(KB_MATERIAL_REVIEW):
        return {}

    items = list(category_queries.items())
    vectors = _embed([query for _category, query in items])
    if not vectors:
        return {}

    hints: dict[str, str] = {}
    max_chars = config.KB_RAG_BASIS_MAX_CHARS
    for (category, _query_text), vector in zip(items, vectors):
        if not _enabled():
            break
        hits = _query(
            KB_MATERIAL_REVIEW, vector, where={"category": category}, top_k=1
        )
        if hits and hits[0].text.strip():
            hints[category] = _normalize_text(hits[0].text, max_chars)

    return hints
