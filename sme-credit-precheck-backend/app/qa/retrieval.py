"""政策问答检索层（从 service.py 搬迁，供政策问答与授信助手共用）。

执行降级链（从强到弱）：
  1. 向量检索（带 where 过滤，命中足够）
  2. 向量检索 + 放宽 where（去掉 product/category 过滤）
  3. 关键词兜底（直接读 YAML 知识库）

本模块只做检索，不做 LLM 生成；授信助手的 search_policy 工具直接复用这里，
避免把政策问答主流程当工具再调一次造成两层 LLM 调用。
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.core import config
from app.rag.kb_retriever import KnowledgeHit, search

logger = logging.getLogger(__name__)


def retrieve_policy_hits(
    kind: str,
    question: str,
    plans: list[Any],  # list[RetrievalPlan]
    *,
    top_k: int | None = None,
) -> tuple[list[KnowledgeHit], list[str], bool]:
    """按降级链检索。

    :param top_k: 覆盖 config.QA_MAX_HITS，助手可传更小值
    :return: (hits, used_collections, fallback_used)
    """
    limit = top_k if top_k is not None else config.QA_MAX_HITS

    # Step 1：执行意图识别给出的 plan（带 where 过滤）
    hits: list[KnowledgeHit] = []
    used_collections: list[str] = []
    for plan in plans:
        try:
            results = search(plan.collection, question, where=plan.where, top_k=plan.top_k)
        except Exception as exc:  # noqa: BLE001
            logger.warning("qa.retrieve step1 失败 collection=%s：%s", plan.collection, exc)
            continue
        if results:
            hits.extend(results)
            used_collections.append(plan.collection)

    if hits:
        hits = _rank_and_dedupe(hits, question)
        take_n = min(len(hits), limit)
        return hits[:take_n], used_collections, False

    # Step 2：去掉 where 过滤再试一次
    logger.info("qa.retrieve step1 零命中，触发 step2 放宽过滤")
    fallback_used = True
    for plan in plans:
        try:
            results = search(plan.collection, question, where=None, top_k=plan.top_k + 1)
        except Exception as exc:  # noqa: BLE001
            logger.warning("qa.retrieve step2 失败 collection=%s：%s", plan.collection, exc)
            continue
        if results:
            hits.extend(results)
            used_collections.append(plan.collection)

    if hits:
        hits = _rank_and_dedupe(hits, question)
        take_n = min(len(hits), limit)
        return hits[:take_n], used_collections, fallback_used

    # Step 3：关键词兜底（纯文本匹配）
    logger.info("qa.retrieve step2 仍零命中，触发 step3 关键词兜底")
    key_hits = _keyword_fallback(plans, question)
    if key_hits:
        hits.extend(key_hits)
        fallback_used = True
        used_collections.append(key_hits[0].collection)

    take_n = min(len(hits), limit)
    return hits[:take_n], used_collections, fallback_used


def _rank_and_dedupe(
    hits: list[KnowledgeHit],
    question: str,
) -> list[KnowledgeHit]:
    """去重 + 打分加权 + 排序。"""
    seen_ids: set[str] = set()
    unique: list[KnowledgeHit] = []
    for h in hits:
        key = f"{h.collection}|{(h.metadata or {}).get('source','')}|{h.text[:60]}"
        if key in seen_ids:
            continue
        seen_ids.add(key)
        unique.append(h)

    tokens = set(re.findall(r"[\u4e00-\u9fa5A-Za-z]{2,}", question))

    def score(hit: KnowledgeHit) -> float:
        s = hit.score
        text_lower = hit.text.lower()
        for tok in tokens:
            if tok.lower() in text_lower:
                s += 0.05
        return s

    unique.sort(key=score, reverse=True)
    return unique


def _keyword_fallback(
    plans: list[Any],
    question: str,
) -> list[KnowledgeHit]:
    """纯关键词兜底：用 kb_retriever.search，但把 query 切成更小的关键词重试。"""
    rule_ids = re.findall(r"\b[A-Z]{2}-[HS]\d{2}\b", question)
    tries: list[str] = []
    for plan in plans:
        hint = getattr(plan, "keyword_hint", "")
        if hint and hint not in tries:
            tries.append(hint)
    if rule_ids:
        tries.extend(rule_ids)
    if not tries:
        # 退化成截取问句前 10 个中文字符
        tries.append(question[:15])

    results: list[KnowledgeHit] = []
    seen: set[str] = set()
    for plan in plans[:3]:
        for kw in tries[:3]:
            if not kw.strip():
                continue
            try:
                batch = search(plan.collection, kw, where=None, top_k=1)
            except Exception:
                continue
            for h in batch:
                key = f"{h.collection}|{h.text[:60]}"
                if key in seen:
                    continue
                seen.add(key)
                results.append(h)
                break  # 每个 (plan, kw) 只吃一条
    return results
