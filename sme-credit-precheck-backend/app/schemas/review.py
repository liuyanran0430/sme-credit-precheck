from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.enums import ReviewDecision
from app.schemas.common import ORMModel


class ReviewItem(BaseModel):
    """单条清单核验结果。"""

    item_id: int = Field(..., description="清单项编号")
    action: str = Field(..., max_length=40, description="核验动作，取值随清单项类型而定")
    comment: str | None = Field(None, max_length=500, description="核验理由（否定性动作必填）")


class ManualReviewCreate(BaseModel):
    """提交人工复核请求体。"""

    reviewer: str = Field(..., max_length=50)
    items: list[ReviewItem]
    decision: Literal["approve", "supplement", "reject"] = Field(
        ..., description="最终复核结论：通过转风控 / 退回补件 / 否决申请"
    )
    comment: str | None = Field(None, description="决策说明（人工覆盖推导结论时必填）")
    supplement_note: str | None = Field(
        None, max_length=500, description="退回补件说明，汇总展示于申请详情页"
    )


class ManualReviewRead(ORMModel):
    id: int
    app_id: int
    reviewer: str
    decision: ReviewDecision
    checklist_result: list[dict[str, Any]] | None
    comment: str | None


class RiskDecisionCreate(BaseModel):
    """提交风控复核决策请求体。"""

    decision: Literal["pass", "reject", "deny"] = Field(
        ..., description="风控决策结论：通过 / 退回补件 / 拒绝"
    )
    opinion: str = Field(..., max_length=2000, description="风控复核意见（必填）")


class RiskReviewRead(ORMModel):
    id: int
    app_id: int
    reviewer: str
    decision: ReviewDecision
    opinion: str
    mitigation: str | None
