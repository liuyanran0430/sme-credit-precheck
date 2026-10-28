from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.models.enums import AiConclusion, ApplicationStatus
from app.schemas.common import ORMModel


class ApplicationBase(ORMModel):
    company_name: str = Field(..., max_length=200, description="企业名称")
    credit_code: str = Field(
        ...,
        min_length=18,
        max_length=18,
        pattern=r"^[0-9A-Z]{18}$",
        description="统一社会信用代码",
    )
    amount: float = Field(..., gt=0, description="申请金额（万元）")
    product: str = Field(..., max_length=100, description="贷款产品")
    manager_name: str | None = Field(None, max_length=50, description="客户经理")


class ApplicationCreate(ApplicationBase):
    """提交新申请请求体。"""


class ApplicationUpdate(BaseModel):
    """申请状态流转请求体。"""

    status: ApplicationStatus = Field(..., description="目标状态")
    remark: str | None = Field(None, description="流转备注")


class ApplicationEdit(BaseModel):
    """修改申请基础信息请求体，字段均可选，至少修改一项。"""

    company_name: str | None = Field(None, max_length=200, description="企业名称")
    credit_code: str | None = Field(
        None,
        min_length=18,
        max_length=18,
        pattern=r"^[0-9A-Z]{18}$",
        description="统一社会信用代码",
    )
    amount: float | None = Field(None, gt=0, description="申请金额（万元）")
    product: str | None = Field(None, max_length=100, description="贷款类型")

    @model_validator(mode="after")
    def _ensure_any_field(self) -> "ApplicationEdit":
        values = self.model_dump(exclude_none=True)
        if not values:
            raise ValueError("至少需要修改一项")
        for key, value in values.items():
            if isinstance(value, str) and not value.strip():
                raise ValueError(f"{key} 不能为空")
        return self


class ApplicationRead(ORMModel):
    id: int
    app_no: str = Field(description="申请编号")
    company_name: str
    credit_code: str | None
    amount: float
    product: str
    status: ApplicationStatus
    manager_name: str | None
    submitted_at: datetime | None
    sla_deadline: datetime | None
    ai_summary: str | None
    supplement_note: str | None
    supplement_source: str | None = None
    risk_returned: bool = Field(
        False, description="是否曾被风控退回补件后重新补齐（非数据表字段）"
    )
    conclusion: AiConclusion | None = Field(
        None, description="最新 AI 预审结论（非数据表字段，由最新预审报告带出）"
    )
    created_at: datetime
