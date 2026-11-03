"""MaterialRepository：材料数据库读写唯一入口。"""

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.models.material import Material


class MaterialRepository:
    """Material 模型的查询与写入。"""

    def __init__(self, db: Session) -> None:
        self.db = db

    # ---- 查询 ----

    def list_by_app(self, app_id: int) -> list[Material]:
        """获取某申请下的全部材料（按 id 升序）。"""
        return list(
            self.db.scalars(
                select(Material)
                .where(Material.app_id == app_id)
                .order_by(Material.id.asc())
            ).all()
        )

    def get_by_id_and_app(self, material_id: int, app_id: int) -> Material | None:
        """按材料 ID + 所属申请 ID 查询（防越权）。"""
        return self.db.scalar(
            select(Material).where(
                Material.id == material_id, Material.app_id == app_id
            )
        )

    # ---- 写入 ----

    def add(self, material: Material, *, flush: bool = True) -> None:
        """新增材料记录到当前事务（不 commit）。"""
        self.db.add(material)
        if flush:
            self.db.flush()

    def commit(self) -> None:
        self.db.commit()

    def refresh(self, material: Material) -> None:
        self.db.refresh(material)

    def refresh_many(self, materials: Sequence[Material]) -> None:
        for m in materials:
            self.db.refresh(m)

    def update_fields(
        self, material: Material, *, commit: bool = True, **fields: object
    ) -> Material:
        """批量更新字段并可选提交。"""
        for key, value in fields.items():
            setattr(material, key, value)
        if commit:
            self.db.commit()
            self.db.refresh(material)
        return material

    def delete(self, material: Material, *, commit: bool = True) -> None:
        """删除单条材料记录。"""
        self.db.delete(material)
        if commit:
            self.db.commit()

    def delete_by_app(self, app_id: int) -> None:
        """删除某申请下全部材料（用于 cascade 删除）。"""
        self.db.execute(delete(Material).where(Material.app_id == app_id))
