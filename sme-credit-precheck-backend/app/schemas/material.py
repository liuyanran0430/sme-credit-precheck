from datetime import datetime

from pydantic import Field

from app.models.enums import MaterialStatus
from app.schemas.ai_classification import MaterialCategory
from app.schemas.common import ORMModel


class MaterialRead(ORMModel):
    id: int
    app_id: int
    category: str = Field(description="材料类别")
    file_name: str
    file_url: str | None
    file_size: int | None
    version: str
    status: MaterialStatus
    confidence: float | None = Field(None, description="AI 分类置信度")
    reason: str | None = Field(None, description="AI 分类依据")
    created_at: datetime


class MaterialUpdate(ORMModel):
    """材料类别人工修正。"""

    category: MaterialCategory = Field(description="修正后的材料类别")
