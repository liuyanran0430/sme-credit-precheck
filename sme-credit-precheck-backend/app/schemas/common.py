from typing import Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ORMModel(BaseModel):
    """支持从 ORM 对象读取属性的基类。"""

    model_config = ConfigDict(from_attributes=True)


class PageQuery(BaseModel):
    """分页查询参数。"""

    page: int = Field(1, ge=1, description="页码，从 1 开始")
    page_size: int = Field(20, ge=1, le=100, description="每页条数")


class Page(BaseModel, Generic[T]):
    """统一分页响应结构。"""

    items: list[T]
    total: int = Field(description="总记录数")
    page: int
    page_size: int


class Message(BaseModel):
    """简单消息响应。"""

    message: str
