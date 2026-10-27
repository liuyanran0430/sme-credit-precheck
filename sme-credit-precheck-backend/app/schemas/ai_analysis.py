"""AI 材料分析的 Pydantic Schema。"""

from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field

from app.models.enums import AiConclusion
from app.schemas.ai_classification import MaterialCategory, OcrResult


class RuleMatchStatus(str, Enum):
    """准入规则匹配结果。"""

    PASS = "pass"
    FAIL = "fail"
    UNCERTAIN = "uncertain"  # 证据不足，转人工


class RiskLevel(str, Enum):
    """风险信号等级。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class ConsistencySeverity(str, Enum):
    """一致性校验严重程度。"""

    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    NONE = "none"


class ConsistencyStatus(str, Enum):
    """一致性校验结论（三态）。"""

    PASS = "pass"  # 一致
    FAIL = "fail"  # 不一致
    UNCERTAIN = "uncertain"  # 字段缺失，无法比对，转人工


class ConflictType(str, Enum):
    """低置信 / 冲突项类型。"""

    LOW_CONFIDENCE = "low_confidence"
    RULE_CONFLICT = "rule_conflict"
    DATA_INCONSISTENT = "data_inconsistent"


class ConflictAction(str, Enum):
    """冲突项处置建议。"""

    MANUAL_REVIEW = "manual_review"


# ---------------------------------------------------------------- 公共输入


class AnalysisMaterial(BaseModel):
    """参与分析的材料。"""

    material_id: int
    material_path: str | None = Field(None, description="材料文件地址")
    category: MaterialCategory
    confidence: float = Field(..., ge=0, le=1, description="分类置信度")
    ocr_result: OcrResult = Field(..., description="字段抽取结果")


class AnalysisContext(BaseModel):
    """申请级上下文。"""

    app_no: str = Field(..., max_length=32, description="申请编号")
    company_name: str = Field(..., max_length=200, description="企业名称")
    credit_code: str | None = Field(None, max_length=32, description="统一社会信用代码")
    apply_amount: float = Field(..., gt=0, description="申请金额（万元）")
    product: str = Field(..., max_length=100, description="贷款产品")
    materials: list[AnalysisMaterial] = Field(
        default_factory=list, description="该申请下的全部材料"
    )


DEFAULT_REQUIRED_CATEGORIES: list[MaterialCategory] = [
    MaterialCategory.BUSINESS_LICENSE,
    MaterialCategory.BANK_STATEMENT,
    MaterialCategory.FINANCIAL_REPORT,
    MaterialCategory.TAX_RETURN,
    MaterialCategory.CREDIT_AUTH,
]


class MaterialAnalysisRequest(BaseModel):
    """材料分析请求：公共输入 + 必交材料清单 + 规则版本。"""

    context: AnalysisContext
    required_categories: list[MaterialCategory] = Field(
        default_factory=lambda: list(DEFAULT_REQUIRED_CATEGORIES),
        description="该产品要求的必交材料清单",
    )
    rule_version: str = Field("v2026-10", max_length=32, description="准入规则版本")


# ---------------------------------------------------- 2.1 完整性 & 一致性


class CategoryCompleteness(BaseModel):
    """单类材料齐全度。"""

    category: MaterialCategory
    label: str
    required: bool = Field(..., description="是否为必备类别")
    count: int = Field(..., ge=0, description="该类材料份数")
    satisfied: bool = Field(..., description="是否满足最小份数要求")


class CompletenessIssue(BaseModel):
    """完整性检查问题项。"""

    type: Literal["missing", "unreadable", "period", "tables"] = Field(
        ..., description="问题类型"
    )
    message: str = Field(..., description="问题说明")


class CompletenessResult(BaseModel):
    """材料完整性判断。"""

    is_complete: bool
    required: list[MaterialCategory] = Field(..., description="必交材料类别")
    missing: list[MaterialCategory] = Field(default_factory=list, description="缺失类别")
    coverage_rate: float = Field(..., ge=0, le=1, description="覆盖率")
    total_materials: int = Field(0, ge=0, description="材料总份数")
    categories: list[CategoryCompleteness] = Field(
        default_factory=list, description="各材料类别齐全度明细"
    )
    issues: list[CompletenessIssue] = Field(
        default_factory=list, description="完整性检查发现的问题"
    )


class ConsistencyValue(BaseModel):
    """同一字段在不同来源中的取值。"""

    source: MaterialCategory | Literal["application"] = Field(
        ..., description="来源材料类别编码，或 application 表示申请信息"
    )
    value: str


class ConsistencyCheck(BaseModel):
    """单项一致性校验。"""

    check_item: str = Field(..., max_length=100, description="校验项名称")
    field: str | None = Field(None, max_length=100, description="比对字段")
    values: list[ConsistencyValue] = Field(default_factory=list, description="各来源取值")
    status: ConsistencyStatus = Field(..., description="校验结论：一致 / 不一致 / 无法判定")
    severity: ConsistencySeverity = Field(..., description="严重程度")
    suggestion: str | None = Field(None, description="处理建议")


class ConsistencyResult(BaseModel):
    """材料一致性判断。"""

    is_consistent: bool
    checks: list[ConsistencyCheck] = Field(default_factory=list)


# ------------------------------------------------------ 2.2 准入规则匹配


class RuleEvidence(BaseModel):
    """规则判定所依据的证据。"""

    source: str | None = Field(None, description="来源材料类别编码")
    field: str | None = Field(None, description="证据字段")
    value: str | float | int | None = Field(None, description="证据取值")


class RuleMatchItem(BaseModel):
    """单条准入规则匹配结果。"""

    rule_id: str = Field(..., max_length=32)
    rule_name: str = Field(..., max_length=200)
    result: RuleMatchStatus
    evidence: RuleEvidence | None = None
    detail: str | None = Field(None, description="判定说明")


class RuleMatchResult(BaseModel):
    """准入规则匹配汇总。"""

    rule_version: str = Field(..., max_length=32)
    pass_count: int = Field(..., ge=0)
    total_count: int = Field(..., ge=0)
    rules: list[RuleMatchItem] = Field(default_factory=list)


# ---------------------------------------------------- 2.3 风险信号汇总


class RiskEvidence(BaseModel):
    """风险信号证据。"""

    source: str | None = Field(None, description="来源材料类别编码")
    detail: str = Field(..., description="证据描述")


class RiskSignal(BaseModel):
    """单条风险信号。"""

    signal_id: str = Field(..., max_length=32)
    level: RiskLevel
    category: str = Field(..., max_length=50, description="风险类别")
    title: str = Field(..., max_length=200)
    evidence: RiskEvidence
    suggestion: str | None = None


class RiskSummary(BaseModel):
    """风险信号汇总。"""

    risk_signals: list[RiskSignal] = Field(default_factory=list)


# ------------------------------------------------ 2.4 低置信 / 规则冲突项


class ConflictItem(BaseModel):
    """低置信、规则冲突或数据不一致项。"""

    type: ConflictType
    source: str | None = Field(None, description="来源材料类别编码")
    field: str | None = Field(None, description="涉及字段")
    value: str | None = Field(None, description="涉及取值")
    confidence: float | None = Field(None, ge=0, le=1, description="置信度")
    rules: list[str] | None = Field(None, description="冲突涉及的规则 ID")
    reason: str = Field(..., description="冲突原因")
    action: ConflictAction = Field(
        ConflictAction.MANUAL_REVIEW, description="处置建议"
    )


class ConflictSummary(BaseModel):
    """低置信 / 冲突项汇总。"""

    conflicts: list[ConflictItem] = Field(default_factory=list)


# ------------------------------------------------------ 3 汇总输出


class AiReportSummary(BaseModel):
    """AI 预审报告头。"""

    conclusion: AiConclusion = Field(..., description="预审结论")
    summary: str = Field(..., description="结论摘要")
    pass_rate: float = Field(..., ge=0, le=100, description="预估通过率（%）")


class MaterialAnalysisResponse(BaseModel):
    """材料分析完整输出，对应 AiReport 的落库字段。"""

    completeness: CompletenessResult
    consistency: ConsistencyResult
    rule_matching: RuleMatchResult
    risk_summary: RiskSummary
    conflict_summary: ConflictSummary
    summary: AiReportSummary
