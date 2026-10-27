from typing import Any

from pydantic import Field

from app.models.enums import AiConclusion
from app.schemas.common import ORMModel


class AiReportRead(ORMModel):
    id: int
    app_id: int
    version: str
    rule_version: str | None
    conclusion: AiConclusion
    summary: str | None
    pass_rate: float | None
    rule_results: list[dict[str, Any]] | None
    risk_signals: list[dict[str, Any]] | None
    conflicts: list[dict[str, Any]] | None
    completeness: dict[str, Any] | None = Field(None, description="材料完整性分析结果")
    consistency: dict[str, Any] | None = Field(None, description="材料一致性分析结果")


class AiReportGenerateRequest(ORMModel):
    """触发 AI 预审的请求体。"""

    rule_version: str | None = Field(None, description="指定规则版本，默认取最新版本")
