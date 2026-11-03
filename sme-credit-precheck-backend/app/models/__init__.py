"""models 包入口——集中 import 所有模型。

Alembic 自动发现表结构时需要 ``Base.metadata`` 包含所有 ORM 表；
``from app.models import Base`` 触发本文件执行，让每个模型模块注册到 ``Base``。
"""

from app.models.base import Base  # noqa: F401

# 集中 import 全项目模型，让 Base.metadata.tables 注册完整
from app.models.application import Application  # noqa: F401,E402
from app.models.llm_run import LLMRun  # noqa: F401,E402
from app.models.material import Material  # noqa: F401,E402
from app.models.report import AiReport  # noqa: F401,E402
from app.models.review import ManualReview, RiskReview  # noqa: F401,E402
from app.models.user import User  # noqa: F401,E402
