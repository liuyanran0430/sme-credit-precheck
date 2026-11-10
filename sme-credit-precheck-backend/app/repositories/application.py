"""ApplicationRepository：申请单数据库读写唯一入口。"""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import delete, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.enums import ApplicationStatus, ReviewDecision
from app.models.report import AiReport
from app.models.review import ManualReview, RiskReview


class ApplicationRepository:
    """Application 模型的查询与写入。

    构造参数：
        db: SQLAlchemy 请求级会话
    """

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- 查询 ----

    def get_by_app_no(self, app_no: str) -> Application | None:
        """按申请编号查询。"""
        return self.db.scalar(
            select(Application).where(Application.app_no == app_no)
        )

    def get_by_id(self, id_: int) -> Application | None:
        """按主键查询。"""
        return self.db.get(Application, id_)

    def list_paginated(
        self,
        *,
        status_filter: ApplicationStatus | None = None,
        product: str | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Application], int, dict[str, int]]:
        """分页查询申请列表，返回 (行, 总数, 全量各状态计数)。

        同时为每行补齐最新 AI 预审结论（conclusion）与风控退回标记（risk_returned）。
        """
        stmt = select(Application)
        if status_filter is not None:
            stmt = stmt.where(Application.status == status_filter)
        if product:
            stmt = stmt.where(Application.product == product.strip())
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    Application.app_no.ilike(like),
                    Application.company_name.ilike(like),
                )
            )

        total = self.db.scalar(
            select(func.count()).select_from(stmt.subquery())
        ) or 0
        rows = self.db.scalars(
            stmt.order_by(Application.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()

        # 全量状态计数
        status_counts = {
            (status.value if isinstance(status, ApplicationStatus) else str(status)): count
            for status, count in self.db.execute(
                select(Application.status, func.count()).group_by(Application.status)
            ).all()
        }

        # 为每行补齐结论与风控退回标记
        if rows:
            conclusion_map = self._latest_conclusions([row.id for row in rows])
            returned_ids = self._risk_returned_app_ids()
            for row in rows:
                row.conclusion = conclusion_map.get(row.id)
                row.risk_returned = row.id in returned_ids

        return list(rows), total, status_counts

    def list_by_status(self, status: ApplicationStatus) -> list[Application]:
        """按状态查询（风控队列等场景）。"""
        return list(
            self.db.scalars(
                select(Application)
                .where(Application.status == status)
                .order_by(Application.id.desc())
            ).all()
        )

    def list_by_manager(
        self,
        manager_name: str,
        *,
        status_filter: ApplicationStatus | None = None,
        keyword: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> tuple[list[Application], int]:
        """按客户经理姓名分页查询本人名下申请，返回 (行, 总数)。

        供授信助手等只读聚合场景使用，数据范围强制限定为 manager_name。
        """
        stmt = select(Application).where(Application.manager_name == manager_name)
        if status_filter is not None:
            stmt = stmt.where(Application.status == status_filter)
        if keyword:
            like = f"%{keyword.strip()}%"
            stmt = stmt.where(
                or_(
                    Application.app_no.ilike(like),
                    Application.company_name.ilike(like),
                )
            )

        total = self.db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
        rows = self.db.scalars(
            stmt.order_by(Application.id.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        ).all()
        return list(rows), total

    def next_app_no(self, prefix: str) -> str:
        """按编号前缀生成同类型申请的下一个编号。"""
        latest_no = self.db.scalar(
            select(Application.app_no)
            .where(Application.app_no.like(f"{prefix}%"))
            .order_by(Application.app_no.desc())
            .limit(1)
        )
        tail = latest_no[len(prefix):] if latest_no else ""
        seq = int(tail) + 1 if tail.isdigit() else 1
        return f"{prefix}{seq:08d}"

    def _latest_conclusions(self, app_ids: Sequence[int]) -> dict[int, object]:
        """批量获取各申请最新一版 AiReport 的结论。"""
        if not app_ids:
            return {}
        latest_report = (
            select(AiReport.app_id, func.max(AiReport.id).label("max_id"))
            .where(AiReport.app_id.in_(list(app_ids)))
            .group_by(AiReport.app_id)
            .subquery()
        )
        return dict(
            self.db.execute(
                select(AiReport.app_id, AiReport.conclusion).join(
                    latest_report,
                    (AiReport.app_id == latest_report.c.app_id)
                    & (AiReport.id == latest_report.c.max_id),
                )
            ).all()
        )

    def _risk_returned_app_ids(self) -> set[int]:
        """曾被风控退回补件的申请 ID 集合。"""
        return set(
            self.db.scalars(
                select(RiskReview.app_id).where(
                    RiskReview.decision == ReviewDecision.REJECT
                )
            ).all()
        )

    # ---- 写入 ----

    def create(
        self,
        *,
        app_no: str,
        company_name: str,
        credit_code: str,
        amount: Decimal,
        product: str,
        manager_name: str,
        status: ApplicationStatus = ApplicationStatus.CHECK,
        ai_summary: str = "申请已提交，等待材料检查与 AI 预审。",
    ) -> Application:
        """创建新申请并提交事务。

        Raises:
            IntegrityError: 申请编号冲突（由调用方捕获并转 409）。
        """
        application = Application(
            app_no=app_no,
            company_name=company_name.strip(),
            credit_code=credit_code.upper(),
            amount=amount,
            product=product,
            status=status,
            manager_name=manager_name,
            sla_deadline=None,
            ai_summary=ai_summary,
        )
        self.db.add(application)
        try:
            self.db.commit()
        except IntegrityError:
            self.db.rollback()
            raise
        self.db.refresh(application)
        return application

    def refresh(self, app: Application) -> None:
        """刷新 ORM 对象以获取最新数据库状态。"""
        self.db.refresh(app)

    def flush(self) -> None:
        """flush 当前事务（不 commit）。"""
        self.db.flush()

    def commit(self) -> None:
        """提交当前事务。"""
        self.db.commit()

    def refresh_many(self, apps: Sequence[Application]) -> None:
        for app in apps:
            self.db.refresh(app)

    def delete_cascade(self, app: Application) -> None:
        """删除申请及其所有关联数据并提交事务。

        级联删除 AiReport / ManualReview / RiskReview / Material，
        不负责文件系统清理（调用方另行处理）。
        """
        for model in (AiReport, ManualReview, RiskReview):
            self.db.execute(delete(model).where(model.app_id == app.id))
        from app.models.material import Material

        self.db.execute(delete(Material).where(Material.app_id == app.id))
        self.db.delete(app)
        self.db.commit()
