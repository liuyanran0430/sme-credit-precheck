"""AI 材料分类与字段抽取的 Pydantic Schema。"""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class MaterialCategory(str, Enum):
    """材料类别统一编码。"""

    BUSINESS_LICENSE = "business_license"  # 营业执照
    BANK_STATEMENT = "bank_statement"  # 银行流水
    FINANCIAL_REPORT = "financial_report"  # 财务报表
    TAX_RETURN = "tax_return"  # 纳税申报表
    CREDIT_AUTH = "credit_auth"  # 征信授权书
    OTHER = "other"  # 其他（兜底类别）


CATEGORY_LABELS: dict[MaterialCategory, str] = {
    MaterialCategory.BUSINESS_LICENSE: "营业执照",
    MaterialCategory.BANK_STATEMENT: "银行流水",
    MaterialCategory.FINANCIAL_REPORT: "财务报表",
    MaterialCategory.TAX_RETURN: "纳税申报表",
    MaterialCategory.CREDIT_AUTH: "征信授权书",
    MaterialCategory.OTHER: "其他",
}

# 低于该阈值时归入 other，转人工分类
LOW_CONFIDENCE_THRESHOLD = 0.6


class MimeType(str, Enum):
    """支持的文件类型。"""

    PDF = "application/pdf"
    JPEG = "image/jpeg"
    PNG = "image/png"


class OcrField(BaseModel):
    """单个抽取字段及其置信度。"""

    value: str | float | int | None = Field(None, description="抽取值")
    confidence: float = Field(..., ge=0, le=1, description="字段置信度")


class OcrResult(BaseModel):
    """OCR / 多模态抽取的结构化结果。"""

    fields: dict[str, OcrField] = Field(
        default_factory=dict, description="按字段名索引的抽取结果"
    )


class MaterialClassifyInput(BaseModel):
    """材料分类与字段抽取的输入。"""

    model_config = ConfigDict(extra="forbid")

    file_name: str = Field(..., max_length=255, description="文件名，作为辅助识别特征")
    mime_type: MimeType = Field(..., description="文件 MIME 类型")
    file_path: str | None = Field(
        None, description="原始文件本地路径或对象存储 URL，与 file_content 二选一"
    )
    file_content: bytes | None = Field(
        None, description="原始文件二进制内容，与 file_path 二选一"
    )

    @model_validator(mode="after")
    def _ensure_file_source(self) -> "MaterialClassifyInput":
        if not self.file_path and self.file_content is None:
            raise ValueError("file_path 与 file_content 至少提供一项")
        return self


class CategoryCandidate(BaseModel):
    """分类候选类别。"""

    category: MaterialCategory = Field(..., description="类别编码")
    label: str = Field(..., max_length=50, description="类别中文标签")
    confidence: float = Field(..., ge=0, le=1, description="类别置信度")


class MaterialClassifyResponse(BaseModel):
    """材料分类与字段抽取的输出。

    边界约定：
    - 置信度 < 0.6 时归入 other，并转人工分类；
    """

    material_id: int = Field(..., description="材料 ID")
    candidate: CategoryCandidate = Field(..., description="单一分类候选结果")
    reason: str | None = Field(None, description="AI 分类依据")
    model_version: str = Field("cls-v1.0", max_length=32, description="模型版本")
