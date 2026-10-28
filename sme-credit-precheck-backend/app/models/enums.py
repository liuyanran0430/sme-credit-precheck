import enum

from sqlalchemy import Enum


class ApplicationStatus(str, enum.Enum):
    """授信申请状态。"""

    CHECK = "check"  # 待材料检查
    SUPPLEMENT = "supplement"  # 待补件
    MANUAL = "manual"  # 待人工核验
    RISK = "risk"  # 待风控复核
    APPROVED = "approved"  # 已审批
    REJECTED = "rejected"  # 已否决


class MaterialStatus(str, enum.Enum):
    """材料抽取状态。"""

    PENDING = "pending"  # 待抽取
    OK = "ok"  # 已抽取
    LOW = "low"  # 低置信
    NONE = "none"  # 暂无文件


class AiConclusion(str, enum.Enum):
    """AI 预审结论。"""

    PASS = "pass"  # 符合
    ATTENTION = "attention"  # 风险建议关注
    FORBIDDEN = "forbidden"  # 建议禁入
    MANUAL = "manual"  # 待人工核验


class ReviewDecision(str, enum.Enum):
    """复核决策结论。"""

    PASS = "pass"  # 通过
    CONDITIONAL = "conditional"  # 有条件通过
    REJECT = "reject"  # 退回补件
    FURTHER = "further"  # 补充调查
    DENY = "deny"  # 否决申请


class UserRole(str, enum.Enum):
    """用户角色。"""

    MANAGER = "manager"  # 客户经理
    RISK = "risk"  # 风控人员
    ADMIN = "admin"  # 管理员


def enum_column(enum_cls: type[enum.Enum], length: int = 20) -> Enum:
    """统一将枚举以 value 字符串形式落库，兼容 SQLite / MySQL。"""
    return Enum(
        enum_cls,
        native_enum=False,
        length=length,
        values_callable=lambda members: [member.value for member in members],
    )
