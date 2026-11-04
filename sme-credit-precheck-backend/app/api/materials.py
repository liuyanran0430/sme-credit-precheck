"""材料管理 endpoints：DB 读写全部调 MaterialRepository。"""

import logging
import time
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_current_user, get_db
from app.core import config
from app.core.logging import LogContext
from app.models.application import Application
from app.models.enums import ApplicationStatus, MaterialStatus
from app.models.user import User
from app.repositories import MaterialRepository
from app.schemas.ai_classification import (
    MaterialClassifyInput,
    MaterialClassifyResponse,
)
from app.schemas.ai_errors import AiErrorResponse
from app.schemas.material import MaterialRead, MaterialUpdate
from app.schemas.task import TaskSubmitResponse
from app.services import task_runner
from app.services.classifier import classify_material
from app.services.material_ingest import ALLOWED_SUFFIXES, SUFFIX_MIME, ingest_materials

logger = logging.getLogger(__name__)

router = APIRouter()

FILE_MEDIA_TYPES = {
    ".pdf": "application/pdf",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
}


@router.get(
    "",
    response_model=list[MaterialRead],
    summary="查询申请材料清单",
)
def list_materials(
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> list[MaterialRead]:
    return MaterialRepository(db).list_by_app(app.id)


@router.get(
    "/{material_id}/file",
    summary="预览材料文件",
    description="内联返回材料原文件，浏览器可直接预览 PDF 与图片。",
    responses={404: {"description": "材料或文件不存在"}},
)
def preview_material(
    material_id: int,
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> FileResponse:
    material = MaterialRepository(db).get_by_id_and_app(material_id, app.id)
    if material is None or not material.file_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="材料不存在")

    file_path = Path(material.file_url)
    if not file_path.is_file():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="文件不存在或已被清理"
        )

    media_type = FILE_MEDIA_TYPES.get(
        Path(material.file_name).suffix.lower(), "application/octet-stream"
    )
    return FileResponse(
        file_path,
        media_type=media_type,
        filename=material.file_name,
        content_disposition_type="inline",
    )


@router.post(
    "/upload",
    response_model=TaskSubmitResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="上传补充材料（异步任务）",
    description=(
        "校验后立即返回 request_id；落盘、OCR 抽取与 AI 分类在后台线程执行，"
        "前端通过 GET /tasks/{request_id} 轮询任务状态，通过 GET materials 轮询处理进度。"
        "AI 预审由前端在材料就绪后调用 /report/generate 触发。"
    ),
)
def upload_materials(
    app: Application = Depends(get_application_or_404),
    user: User = Depends(get_current_user),
    files: list[UploadFile] = File(..., description="待上传的材料文件"),
) -> TaskSubmitResponse:
    # 注意：本接口必须是同步 def（FastAPI 会放入线程池执行），不能改成 async def。
    # 请求线程只做文件校验与读取；OCR/LLM/DB 等耗时处理全部移入后台任务线程，
    # 避免请求挂起数十秒导致代理超时。
    max_bytes = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    pending: list[tuple[str, bytes]] = []

    for file in files:
        filename = Path(file.filename or "unnamed").name
        if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的文件格式：{filename}",
            )
        content = file.file.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{filename} 超过 {config.MAX_UPLOAD_SIZE_MB}MB",
            )
        pending.append((filename, content))

    # user_id 写入日志上下文，后台线程继承后 LLM 结构化日志可定位到操作人
    with LogContext(app_no=app.app_no, user_id=user.id, user=user.username):
        request_id = task_runner.submit(
            app.app_no,
            task_runner.TASK_TYPE_MATERIALS_UPLOAD,
            lambda db: ingest_materials(db, app.id, app.app_no, pending),
        )
    return TaskSubmitResponse(request_id=request_id, app_no=app.app_no)


@router.post(
    "/{material_id}/classify",
    response_model=MaterialClassifyResponse,
    summary="AI 材料分类",
    description="对已上传材料执行 AI 分类，回写类别、置信度、分类依据与 OCR 文本，状态置为已抽取。",
    responses={400: {"model": AiErrorResponse}, 404: {"description": "材料不存在"}},
)
def classify_material_endpoint(
    material_id: int,
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> MaterialClassifyResponse:
    # 状态守卫：材料检查中禁止重新分类，避免与后台分类任务并发写同一材料
    if app.status == ApplicationStatus.CHECK:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="材料检查中，暂不可修改分类",
        )
    mat_repo = MaterialRepository(db)
    material = mat_repo.get_by_id_and_app(material_id, app.id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="材料不存在")

    mime_type = SUFFIX_MIME.get(Path(material.file_name).suffix.lower())
    if mime_type is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"不支持的文件格式：{material.file_name}",
        )

    payload = MaterialClassifyInput(
        file_name=material.file_name,
        mime_type=mime_type,
        file_path=material.file_url,
    )
    with LogContext(app_no=app.app_no):
        t0 = time.perf_counter()
        result, text = classify_material(payload, material.id, text=material.ocr_text)
        classify_elapsed = time.perf_counter() - t0
        top = result.candidate
        mat_repo.update_fields(
            material,
            category=top.category.value,
            confidence=Decimal(str(top.confidence)),
            reason=result.reason,
            ocr_text=text or material.ocr_text,
            status=MaterialStatus.OK,
        )

        logger.info(
            "重新分类材料, app_no=%s, 材料ID=%d, 文件名=%s → %s, 置信度=%.2f, 耗时=%.2fs",
            app.app_no,
            material_id,
            material.file_name,
            top.category.value,
            top.confidence,
            classify_elapsed,
        )

    return result


@router.patch(
    "/{material_id}",
    response_model=MaterialRead,
    summary="修改材料类别",
    description="人工修正材料类别（如将「其他」中的文件归入正确类别）。",
    responses={404: {"description": "材料不存在"}},
)
def update_material(
    material_id: int,
    payload: MaterialUpdate,
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> MaterialRead:
    # 状态守卫：材料检查中（后台 OCR/AI 分类写入中）禁止人工修改分类，避免写入冲突
    if app.status == ApplicationStatus.CHECK:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="材料检查中，暂不可修改分类",
        )
    mat_repo = MaterialRepository(db)
    material = mat_repo.get_by_id_and_app(material_id, app.id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="材料不存在")

    return mat_repo.update_fields(material, category=payload.category.value)


@router.delete(
    "/{material_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除材料",
    description="删除材料记录并清理对应的上传文件，随后自动重新执行 AI 预审并同步申请状态。",
    responses={404: {"description": "材料不存在"}},
)
def delete_material(
    material_id: int,
    app: Application = Depends(get_application_or_404),
    db: Session = Depends(get_db),
) -> Response:
    mat_repo = MaterialRepository(db)
    material = mat_repo.get_by_id_and_app(material_id, app.id)
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="材料不存在")

    file_url = material.file_url
    mat_repo.delete(material)

    if file_url:
        file_path = Path(file_url)
        if file_path.is_file():
            file_path.unlink()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
