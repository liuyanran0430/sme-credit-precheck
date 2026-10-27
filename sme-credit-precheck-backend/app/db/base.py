"""集中导入所有模型，供 Alembic 自动生成迁移时发现元数据。"""

from app.db.base_class import Base  # noqa: F401
from app.models.application import Application  # noqa: F401
from app.models.material import Material  # noqa: F401
from app.models.report import AiReport  # noqa: F401
from app.models.review import ManualReview, RiskReview  # noqa: F401
from app.models.user import User  # noqa: F401
