"""政策问答 Agent 的 Pydantic Schema。

请求/响应字段均面向 HTTP 层：chat_history 由前端传入，服务层自行截断；
references 列表按知识库片段顺序返回，response.answer 中的 [1][2] 与之对应。
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field


class QaMessage(BaseModel):
    """单条历史对话（角色固定 user/assistant）。"""

    role: str = Field(..., pattern=r"^(user|assistant)$", description="角色")
    content: str = Field(..., min_length=1, max_length=5000, description="对话内容")


class QaRequest(BaseModel):
    """单轮问答请求。"""

    question: str = Field(..., min_length=1, max_length=500, description="用户问题")
    product: str | None = Field(None, max_length=50, description="产品中文名（可选，用于检索过滤）")
    category: str | None = Field(
        None, max_length=50, description="材料类别编码（可选，用于检索过滤）"
    )
    chat_history: list[QaMessage] | None = Field(
        None, description="最近对话历史，服务端自动截断到 QA_MAX_HISTORY_TURNS"
    )


class ReferenceItem(BaseModel):
    """单条引用：与 answer 中的 [index] 一一对应。"""

    index: int = Field(..., ge=1, description="引用编号，从 1 开始")
    kind: Literal["policy", "business"] = Field(
        "policy", description="引用类型：policy=知识库原文，business=业务数据"
    )
    collection: str = Field(..., description="来源 collection 名：kb_policy / kb_material_review / ...")
    source: str = Field(..., description="知识库相对路径（如 01_信贷政策/准入规则/普惠小微经营贷.md）")
    rule_id: str | None = Field(None, description="命中的规则编号（若有）")
    product: str | None = Field(None, description="命中的产品（若有）")
    excerpt: str = Field(..., description="命中文本截取（约 100 字）")


class QaResponse(BaseModel):
    """问答响应。"""

    answer: str = Field(..., description="自然语言回答")
    references: list[ReferenceItem] = Field(default_factory=list, description="引用列表")
    confidence: float = Field(..., ge=0.0, le=1.0, description="0~1，检索+生成整体置信度")
    used_collections: list[str] = Field(default_factory=list, description="实际命中的 collection")
    fallback_used: bool = Field(False, description="是否触发了降级链（放宽过滤或关键词兜底）")
    model: str = Field("deepseek-chat", description="实际使用的 LLM 模型名")
    request_id: str = Field("", description="本次请求 ID，用于日志与排错")
    hint: str | None = Field(
        None, description="引导提示：命中个人化业务问题时提示改用授信助手（默认 null）"
    )


class SuggestionResponse(BaseModel):
    """推荐问题气泡（静态返回）。"""

    questions: list[str] = Field(..., description="推荐问题列表，最多 6 条")
