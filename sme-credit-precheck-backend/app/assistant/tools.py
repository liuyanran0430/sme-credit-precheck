"""授信助手工具注册表与 JSON Schema。

P0 只读工具：
- list_my_applications   查询本人名下申请（分页）
- get_application_detail 查询单笔申请基础信息 + 材料概要（强制归属校验）
- get_precheck_summary   读取已落库的 AI 预审快照摘要

P1 只读工具：
- list_products          查询在售产品与一句话特征
- preview_eligibility    准入预演（规则引擎纯计算，不落库）
- get_required_materials 产品级必交材料清单
- search_policy          知识库政策检索（复用政策问答检索层）

P2 只读工具：
- list_my_todos          本人名下待办主动汇总（按状态分组）
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

ToolName = Literal[
    "list_my_applications",
    "get_application_detail",
    "get_precheck_summary",
    "list_products",
    "preview_eligibility",
    "get_required_materials",
    "search_policy",
    "list_my_todos",
    "list_review_queue",
    "none",
]


class PlannedCall(BaseModel):
    """LLM 规划出的一次工具调用。"""

    tool: ToolName = Field(..., description="工具名；无需调用时填 none")
    app_id: int | None = Field(None, description="申请主键（get_*_summary / 预演已上传申请时必填）")
    status: str | None = Field(
        None,
        description="申请状态过滤：check/precheck/supplement/manual/risk/approved/rejected，"
        "也接受中文（待补件 / 待人工核验 / 待风控复核 等）",
    )
    keyword: str | None = Field(None, description="申请编号或企业名称关键字")
    product: str | None = Field(
        None, description="产品中文名：普惠小微经营贷 / 小微快贷 / 经营性抵押贷 / 科技e贷"
    )
    query: str | None = Field(None, description="政策检索问句（search_policy 必填）")
    category: str | None = Field(
        None, description="材料类别编码：business_license / bank_statement / ..."
    )
    profile: str | None = Field(
        None,
        description="企业概况原文（preview_eligibility 无 app_id 时使用），"
        "如「年营收 800 万、成立 3 年、资产负债率 60%、申请 100 万」",
    )


class ToolPlan(BaseModel):
    """一轮规划结果。"""

    calls: list[PlannedCall] = Field(default_factory=list, description="本轮需要调用的工具")
    reason: str = Field("", description="为什么调用这些工具，一句话")


# 供 Planner Prompt 展示的工具清单（名称 + 说明 + 参数）
TOOL_SPECS: list[dict[str, Any]] = [
    {
        "name": "list_my_applications",
        "description": "查询当前客户经理本人名下的申请列表（分页，最多返回 10 条），"
        "支持按状态和关键字过滤。适合回答「我有几笔待补件」「我最近有哪些申请」。",
        "parameters": {
            "status": "可选，申请状态：check / precheck / supplement / manual / risk / approved / rejected",
            "keyword": "可选，申请编号或企业名称关键字",
        },
    },
    {
        "name": "get_application_detail",
        "description": "查询单笔申请的详细信息与材料清单概要。必须提供 app_id。"
        "只能查询当前客户经理本人名下的申请。",
        "parameters": {"app_id": "必填，申请主键（整数）"},
    },
    {
        "name": "get_precheck_summary",
        "description": "读取单笔申请已落库的 AI 预审摘要：结论等级、通过率、未通过规则、"
        "风险信号、冲突项、缺失材料。不得自行推断，只能引用工具结果。必须提供 app_id。",
        "parameters": {"app_id": "必填，申请主键（整数）"},
    },
    {
        "name": "list_products",
        "description": "列出当前在售的信贷产品及一句话特征，适合回答"
        "「能做哪个产品」「有哪些产品」这类选产品问题。",
        "parameters": {},
    },
    {
        "name": "preview_eligibility",
        "description": "准入预演：按产品规则逐条预判符合 / 不符合 / 存疑，并列出缺失字段。"
        "已有申请时传 app_id（基于已上传材料预演）；仅口头描述企业概况时传 profile 原文。"
        "结果为规则引擎预演，不落库、不代表正式审批。必须提供 product。",
        "parameters": {
            "product": "必填，产品中文名",
            "app_id": "可选，已上传材料的申请主键",
            "profile": "可选，企业概况原文（无 app_id 时使用）",
        },
    },
    {
        "name": "get_required_materials",
        "description": "查询某个产品申请前需要准备的必交材料类别与每类审核要点。必须提供 product。",
        "parameters": {"product": "必填，产品中文名"},
    },
    {
        "name": "search_policy",
        "description": "检索知识库政策原文与规则配置，用于回答准入要求、材料审核标准、"
        "规则编号解释等纯政策问题。必须提供 query。",
        "parameters": {
            "query": "必填，检索问句",
            "product": "可选，限定产品",
            "category": "可选，限定材料类别编码",
        },
    },
    {
        "name": "list_my_todos",
        "description": "汇总当前客户经理本人名下的待办申请（待补件 / 待人工核验 / 待 AI 预审 / "
        "待材料检查），按优先级列出需要处理的申请。适合回答「我有哪些待办」"
        "「这周要处理什么」。",
        "parameters": {},
    },
    {
        "name": "list_review_queue",
        "description": "查询当前待风控复核队列中的申请列表（不限客户经理，按提交时间排序）。"
        "适合回答「有哪些待复核」「复核队列有哪些」「今天要复核什么」。",
        "parameters": {},
    },
]

TOOL_NAMES: set[str] = {spec["name"] for spec in TOOL_SPECS}

# 按角色划分的工具白名单——两个 Agent 能力边界明确不同，不是同一套工具换名字。
# 客户经理：偏流程办理、材料准备、本人名下数据
MANAGER_TOOL_NAMES: frozenset[str] = frozenset({
    "list_my_applications",
    "get_application_detail",
    "get_precheck_summary",
    "list_products",
    "preview_eligibility",
    "get_required_materials",
    "search_policy",
    "list_my_todos",
})

# 风控复核员：偏风险信息汇总、复核队列、政策依据；不提供材料准备/准入预演/本人待办
RISK_TOOL_NAMES: frozenset[str] = frozenset({
    "list_review_queue",
    "get_application_detail",
    "get_precheck_summary",
    "list_products",
    "search_policy",
})
