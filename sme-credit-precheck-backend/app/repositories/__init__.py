"""Repository 层：数据库读写唯一入口。

每个 Repository 类封装一个或多个 ORM 模型的查询和写入操作。
上层（endpoints / services）只通过 Repository 方法与数据库交互，
不再直接写 SQLAlchemy 查询或调用 db.add/commit/refresh。

设计原则：
- 构造函数接收 db: Session（请求级会话，由 FastAPI Depends 注入）
- 查询方法返回 ORM 对象或标量值，**不做 404 等业务判断**
- 写入方法的 commit 参数控制是否立即提交（默认 True），
  需要多表事务时传 commit=False 由调用方统一 commit
- refresh 在需要返回最新状态时自动调用
"""

from .application import ApplicationRepository
from .material import MaterialRepository
from .report import ReportRepository
from .review import ReviewRepository
from .user import UserRepository

__all__ = [
    "ApplicationRepository",
    "MaterialRepository",
    "ReportRepository",
    "ReviewRepository",
    "UserRepository",
]
