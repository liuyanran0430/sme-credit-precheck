"""ReportRepository：AI 预审报告数据库读写唯一入口。"""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.report import AiReport


class ReportRepository:
    """AiReport 模型的查询与写入。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- 查询 ----

    def get_latest_by_app(self, app_id: int) -> AiReport | None:
        """获取某申请最新一版 AI 预审报告。"""
        return self.db.scalar(
            select(AiReport)
            .where(AiReport.app_id == app_id)
            .order_by(AiReport.id.desc())
        )

    def list_by_app(self, app_id: int) -> list[AiReport]:
        """获取某申请全部 AI 预审报告（按 id 倒序）。"""
        return list(
            self.db.scalars(
                select(AiReport)
                .where(AiReport.app_id == app_id)
                .order_by(AiReport.id.desc())
            ).all()
        )

    def latest_conclusions(self, app_ids: Sequence[int]) -> dict[int, object]:
        """批量获取各申请最新一版报告的结论（供列表页展示）。"""
        if not app_ids:
            return {}
        latest = (
            select(AiReport.app_id, func.max(AiReport.id).label("max_id"))
            .where(AiReport.app_id.in_(list(app_ids)))
            .group_by(AiReport.app_id)
            .subquery()
        )
        return dict(
            self.db.execute(
                select(AiReport.app_id, AiReport.conclusion).join(
                    latest,
                    (AiReport.app_id == latest.c.app_id)
                    & (AiReport.id == latest.c.max_id),
                )
            ).all()
        )

    # ---- 写入 ----

    def upsert_for_app(
        self,
        app_id: int,
        *,
        conclusion: object,
        summary: str,
        pass_rate: Decimal,
        completeness: dict,
        consistency: dict,
        rule_results: dict,
        risk_signals: list[dict],
        conflicts: list[dict],
        rule_version: str | None,
        rule_snapshot: dict | None,
        interpretation_text: str | None = None,
        version: str = "v1",
        commit: bool = True,
    ) -> AiReport:
        """为某申请创建或更新最新一版预审报告。

        commit=False 时调用方需自行提交事务（用于与 Application 状态更新同事务提交）。
        """
        report = self.db.scalar(
            select(AiReport)
            .where(AiReport.app_id == app_id)
            .order_by(AiReport.id.desc())
        )
        if report is None:
            report = AiReport(app_id=app_id, version=version)
            self.db.add(report)

        report.conclusion = conclusion
        report.summary = summary
        report.pass_rate = pass_rate
        report.completeness = completeness
        report.consistency = consistency
        report.rule_results = rule_results
        report.risk_signals = risk_signals
        report.conflicts = conflicts
        report.rule_version = rule_version
        report.rule_snapshot = rule_snapshot
        report.interpretation_text = interpretation_text

        if commit:
            self.db.commit()
            self.db.refresh(report)
        return report
