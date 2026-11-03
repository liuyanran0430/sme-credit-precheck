"""ReviewRepository：人工复核 / 风控复核数据库读写唯一入口。"""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.application import Application
from app.models.enums import ApplicationStatus, ReviewDecision
from app.models.review import ManualReview, RiskReview


class ReviewRepository:
    """ManualReview / RiskReview 模型的查询与写入。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- 查询 ----

    def list_manual_by_app(self, app_id: int) -> list[ManualReview]:
        """获取某申请全部人工复核记录（按 id 倒序）。"""
        return list(
            self.db.scalars(
                select(ManualReview)
                .where(ManualReview.app_id == app_id)
                .order_by(ManualReview.id.desc())
            ).all()
        )

    def list_risk_by_app(self, app_id: int) -> list[RiskReview]:
        """获取某申请全部风控复核记录（按 id 倒序）。"""
        return list(
            self.db.scalars(
                select(RiskReview)
                .where(RiskReview.app_id == app_id)
                .order_by(RiskReview.id.desc())
            ).all()
        )

    def list_risk_queue(self) -> list[Application]:
        """风控复核队列：所有处于 RISK 状态的申请。"""
        return list(
            self.db.scalars(
                select(Application)
                .where(Application.status == ApplicationStatus.RISK)
                .order_by(Application.id.desc())
            ).all()
        )

    def risk_returned_app_ids(self) -> set[int]:
        """曾被风控退回补件的申请 ID 集合。"""
        return set(
            self.db.scalars(
                select(RiskReview.app_id).where(
                    RiskReview.decision == ReviewDecision.REJECT
                )
            ).all()
        )

    # ---- 写入 ----

    def create_manual(self, review: ManualReview) -> ManualReview:
        """提交人工复核记录并返回已刷新对象。"""
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review

    def create_risk(self, review: RiskReview) -> RiskReview:
        """提交风控复核记录并返回已刷新对象。"""
        self.db.add(review)
        self.db.commit()
        self.db.refresh(review)
        return review
