from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import ReviewDecision
from app.schemas.common import ORMModel


class ReviewItem(BaseModel):
    """单条清单复核结果。"""

    item_id: int = Field(..., description="清单项编号")
    result: Literal["adopt", "modify", "reject"] = Field(..., description="采纳 / 修改 / 推翻")
    comment: str | None = Field(None, description="复核理由")


class ManualReviewCreate(BaseModel):
    """提交人工复核请求体。"""

    reviewer: str = Field(..., max_length=50)
    items: list[ReviewItem]
    comment: str | None = None


class ManualReviewRead(ORMModel):
    id: int
    app_id: int
    reviewer: str
    decision: ReviewDecision
    checklist_result: list[dict[str, Any]] | None
    comment: str | None


class RiskDecisionCreate(BaseModel):
    """提交风控复核决策请求体。"""

    reviewer: str = Field(..., max_length=50)
    decision: ReviewDecision
    opinion: str = Field(..., description="风控复核意见")
    mitigation: str | None = Field(None, max_length=500, description="风险缓释条件")


class RiskReviewRead(ORMModel):
    id: int
    app_id: int
    reviewer: str
    decision: ReviewDecision
    opinion: str
    mitigation: str | None
