"""AI 能力统一错误输出 Schema。"""

from enum import Enum

from pydantic import BaseModel, Field


class AiErrorPrefix(str, Enum):
    """错误码前缀约定。"""

    CLASSIFY = "AI_CLS"  # 分类失败：文件损坏 / 格式不支持 / 页数超限
    OCR = "AI_OCR"  # 抽取失败：模糊 / 加密 PDF / 手写体
    ANALYSIS = "AI_ANL"  # 分析失败：规则版本缺失 / 上下文不全


class AiErrorResponse(BaseModel):
    """AI 能力统一错误响应。"""

    code: str = Field(
        ...,
        pattern=r"^AI_(CLS|OCR|ANL)_\d{3}$",
        description="错误码，如 AI_CLS_001",
    )
    message: str = Field(..., description="错误描述")
    material_id: int | None = Field(None, description="关联材料 ID")
    recoverable: bool = Field(True, description="是否可通过重试 / 重新上传恢复")
    suggestion: str | None = Field(None, description="处理建议")
