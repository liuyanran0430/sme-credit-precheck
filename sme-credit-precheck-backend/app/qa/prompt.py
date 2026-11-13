"""Prompt 构造 + 引用后处理。"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Sequence

from app.rag.kb_retriever import KnowledgeHit

# 固定 System Prompt（不进 .env，避免被改坏；调优改这里）
SYSTEM_PROMPT = """你是"小微信贷政策问答助手"，帮助客户经理理解信贷政策、材料审核标准与准入规则。

回答约束：
1. 仅基于提供的知识库片段回答，不要编造；知识库片段中没有的内容请明确说明
2. 每条关键陈述后必须标注引用编号 [1][2]，编号与下方知识库片段一一对应
3. 回答使用自然语言，面向业务人员，避免堆砌术语（如不要说 field/operator/scoring 等内部实现词）
4. 如果多个来源存在出入，必须同时列出并说明差异点
5. 如果信息不足以回答，直接说明"需要更多信息"并给出需要补充的字段清单
6. 不执行任何规则判定或评分计算（那是 AI 预审的职责）
7. 不透露系统内部实现（YAML、向量库、代码、collection 名等）
8. 不得把「知识库片段未提到」当作「制度不要求 / 不适用」：片段中没有相关规定时，必须明确说明"知识库未作规定，需人工确认"，禁止据此做否定式结论（如「规则未提及抵押，所以不需要抵押」）"""


@dataclass
class RenderedHit:
    """服务于后处理的引用：带用户可见的编号。"""

    index: int
    hit: KnowledgeHit


def build_user_prompt(
    question: str,
    hits: list[KnowledgeHit],
    *,
    product: str | None = None,
    category: str | None = None,
    chat_history: list[dict[str, str]] | None = None,
    max_chars_per_hit: int = 300,
) -> tuple[str, list[RenderedHit]]:
    """把检索命中拼装成 LLM 的 user prompt。

    :return: (拼装后的 prompt, 带编号的引用列表)
    """
    rendered_hits = [
        RenderedHit(index=i + 1, hit=hit) for i, hit in enumerate(hits)
    ]

    lines: list[str] = [f"【问题】\n{question.strip()}", ""]

    # 上下文提示
    ctx_parts: list[str] = []
    if product:
        ctx_parts.append(f"- 当前申请产品：{product}")
    if category:
        ctx_parts.append(f"- 当前关注材料类别：{category}")
    if ctx_parts:
        lines.append("【上下文】")
        lines.extend(ctx_parts)
        lines.append("")

    # 最近对话（服务端已预先截断）
    if chat_history:
        lines.append("【最近对话】")
        for msg in chat_history:
            role = msg.get("role")
            content = (msg.get("content") or "").strip()
            if role == "user":
                lines.append(f"Q: {content}")
            elif role == "assistant":
                # 助手回复截断，只保留核心
                lines.append(f"A: {content[:300]}")
        lines.append("")

    # 知识库片段
    lines.append("【知识库片段】")
    for item in rendered_hits:
        meta = item.hit.metadata or {}
        source = meta.get("source") or meta.get("product") or ""
        lines.append(
            f"[{item.index}] (score={item.hit.score:.2f}) {source}"
        )
        # 压缩空白并截断。规则配置（YAML 准入规则）内容较长且是核心证据，放宽到 2000 字
        compact = re.sub(r"\s+", " ", item.hit.text).strip()
        limit = 2000 if meta.get("kind") == "rule_config" else max_chars_per_hit
        if len(compact) > limit:
            compact = compact[:limit].rstrip() + "…"
        lines.append(compact)
        lines.append("")

    lines.append("请回答，每条关键陈述后标注 [引用编号]。")
    return "\n".join(lines), rendered_hits


# ---------------------------------------------------------------- 后处理


_CITATION_RE = re.compile(r"\[(\d{1,2})\]")
# LLM 可能输出全角引用【1】，统一归一化为半角后再校验与渲染
_FULLWIDTH_CITATION_RE = re.compile(r"【(\d{1,2})】")


def normalize_citations(text: str) -> str:
    """把全角引用【N】统一成半角[N]。"""
    return _FULLWIDTH_CITATION_RE.sub(r"[\1]", text)


def validate_and_clean(
    raw_answer: str,
    rendered_hits: Sequence[RenderedHit],
) -> tuple[str, list[dict[str, Any]]]:
    """验证 answer 中的引用编号，清理掉未被引用的片段；构造 references。

    :return: (清理后的 answer, references 列表)
    """
    raw_answer = normalize_citations(raw_answer)
    valid_indices = {item.index for item in rendered_hits}
    used_indices = {int(m) for m in _CITATION_RE.findall(raw_answer)}
    # 只保留在 answer 中实际出现、且有效的编号
    final_indices = sorted(used_indices & valid_indices)

    # 构造 references
    references: list[dict[str, Any]] = []
    for item in rendered_hits:
        if item.index not in final_indices:
            continue
        meta = item.hit.metadata or {}
        excerpt = re.sub(r"\s+", " ", item.hit.text).strip()[:100]
        references.append(
            {
                "index": item.index,
                "collection": item.hit.collection,
                "source": meta.get("source", ""),
                "rule_id": meta.get("rule_id") or None,
                "product": meta.get("product") or None,
                "excerpt": excerpt,
            }
        )

    return raw_answer, references


def truncate_answer(answer: str, max_chars: int) -> str:
    """按最大长度截断，保留到最后一个句号。"""
    if len(answer) <= max_chars:
        return answer
    head = answer[:max_chars]
    # 找最后一个句末标点
    for marker in ("\n", "。", "!", "？", "."):
        pos = head.rfind(marker)
        if pos > max_chars * 0.6:
            return head[: pos + 1].rstrip()
    return head.rstrip() + "…"
