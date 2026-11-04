"""材料入库与 OCR/AI 分类处理（供后台任务线程调用）。

两阶段写入：
- 阶段 1：全部落盘 + INSERT（status=pending）后立即 commit，前端轮询可立即看到完整文件列表
- 阶段 2：串行 OCR + AI 分类，每个文件处理完立即 commit，前端可实时看到进度递增
全部完成后将申请状态 check → precheck。
"""

import logging
import time
import uuid
from decimal import Decimal
from pathlib import Path

from sqlalchemy.orm import Session

from app.core import config
from app.core.logging import LogContext
from app.models.application import Application
from app.models.enums import ApplicationStatus, MaterialStatus
from app.models.material import Material
from app.repositories import MaterialRepository
from app.schemas.ai_classification import MaterialClassifyInput, MimeType
from app.services.classifier import classify_material

logger = logging.getLogger(__name__)

SUFFIX_MIME = {
    ".pdf": MimeType.PDF,
    ".jpg": MimeType.JPEG,
    ".jpeg": MimeType.JPEG,
    ".png": MimeType.PNG,
}
ALLOWED_SUFFIXES = set(SUFFIX_MIME)


def ingest_materials(
    db: Session,
    app_id: int,
    app_no: str,
    pending_files: list[tuple[str, bytes]],
) -> None:
    """落盘 + INSERT pending + 串行 OCR/分类（在后台线程中执行，db 由调用方管理）。"""
    upload_root = Path(config.UPLOAD_DIR) / app_no
    upload_root.mkdir(parents=True, exist_ok=True)

    mat_repo = MaterialRepository(db)

    with LogContext(app_no=app_no):
        # ===== 阶段 1：落盘 + INSERT（status=pending） =====
        materials: list[Material] = []
        for filename, content in pending_files:
            stored_name = f"{uuid.uuid4().hex}_{filename}"
            file_url = f"{config.UPLOAD_DIR}/{app_no}/{stored_name}".replace("\\", "/")
            (upload_root / stored_name).write_bytes(content)
            material = Material(
                app_id=app_id,
                category="other",
                file_name=filename,
                file_url=file_url,
                file_size=len(content),
                version="v1.0",
                status=MaterialStatus.PENDING,
            )
            mat_repo.add(material, flush=False)
            materials.append(material)

            logger.info(
                "上传材料, app_no=%s, 文件名=%s, 大小=%.1fMB",
                app_no,
                filename,
                len(content) / 1024 / 1024,
            )

        # 阶段 1 结束：flush + commit，让 INSERT 先持久化
        # 这样即使阶段 2 分类全部失败，材料记录也不会丢
        db.flush()
        db.commit()
        logger.info(
            "阶段1完成：已插入 %d 条材料记录（status=pending），app_no=%s",
            len(materials),
            app_no,
        )

        # ===== 阶段 2：串行 OCR + AI 分类（逐个 UPDATE + 逐个 commit） =====
        # 前端在材料检查阶段轮询 materials 接口，实时看到 ok/fail 数量逐步增加
        logger.info("阶段2开始：串行 OCR + AI 分类 %d 个文件, app_no=%s", len(materials), app_no)
        for material in materials:
            try:
                t0 = time.perf_counter()
                payload = MaterialClassifyInput(
                    file_name=material.file_name,
                    mime_type=SUFFIX_MIME[Path(material.file_name).suffix.lower()],
                    file_path=material.file_url,
                )
                result, text = classify_material(payload, material.id)
                classify_elapsed = time.perf_counter() - t0
                top = result.candidate
                material.category = top.category.value
                material.confidence = Decimal(str(top.confidence))
                material.reason = result.reason
                material.ocr_text = text or None
                material.status = MaterialStatus.OK

                logger.info(
                    "AI 分类完成, 材料ID=%d, 结果=%s, 置信度=%.2f, 耗时=%.2fs",
                    material.id,
                    top.category.value,
                    top.confidence,
                    classify_elapsed,
                )
            except Exception as exc:
                # 单个文件失败 → 标记 fail + 继续下一个，不 ROLLBACK 整批
                material.status = MaterialStatus.FAIL
                material.reason = f"OCR/AI 分类失败：{exc}"
                logger.warning(
                    "AI 分类失败, 材料ID=%d, 文件名=%s, 错误=%s",
                    material.id,
                    material.file_name,
                    exc,
                )

            # 每个文件处理完立即 commit，让前端轮询逐步看到 status/category 更新
            try:
                db.commit()
            except Exception as exc:
                logger.warning("commit 失败（继续下一个）, 错误=%s", exc)
                db.rollback()

        # 所有材料抽取完成后，将 check → precheck，等待用户手动触发 AI 预审
        logger.info("阶段2完成：开始检查 pending 状态材料, app_no=%s", app_no)
        still_pending = (
            db.query(Material)
            .filter(Material.app_id == app_id, Material.status == MaterialStatus.PENDING)
            .count()
        )
        app = db.get(Application, app_id)
        if still_pending == 0 and app is not None and app.status == ApplicationStatus.CHECK:
            app.status = ApplicationStatus.PRECHECK
            db.commit()
            logger.info("材料检查完成，申请状态 check → precheck, app_no=%s", app_no)
        else:
            logger.info(
                "跳过 check→precheck 推进: still_pending=%d, app.status=%s, app_no=%s",
                still_pending,
                app.status.value if app is not None else "missing",
                app_no,
            )
