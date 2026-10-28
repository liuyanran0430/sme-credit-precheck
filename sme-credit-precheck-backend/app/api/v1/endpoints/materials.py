import uuid
from decimal import Decimal
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_application_or_404, get_db
from app.core import config
from app.models.application import Application
from app.models.enums import MaterialStatus
from app.models.material import Material
from app.schemas.ai_classification import (
    MimeType,
    MaterialClassifyInput,
    MaterialClassifyResponse,
)
from app.schemas.ai_errors import AiErrorResponse
from app.schemas.material import MaterialRead, MaterialUpdate
from app.services.analyzer import generate_report
from app.services.classifier import classify_material

router = APIRouter()

SUFFIX_MIME = {
    ".pdf": MimeType.PDF,
    ".jpg": MimeType.JPEG,
    ".jpeg": MimeType.JPEG,
    ".png": MimeType.PNG,
}
ALLOWED_SUFFIXES = set(SUFFIX_MIME)

# 预览响应的媒体类型（与 SUFFIX_MIME 的枚举值不同，此处为浏览器 MIME 类型）
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
    rows = db.scalars(
        select(Material).where(Material.app_id == app.id).order_by(Material.id.asc())
    ).all()
    return list(rows)


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
    material = db.scalar(
        select(Material).where(Material.id == material_id, Material.app_id == app.id)
    )
    if material is None or not material.file_url:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="材料不存在")

    # file_url 为服务端生成的相对路径，非用户输入，无路径穿越风险
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
    response_model=list[MaterialRead],
    status_code=status.HTTP_201_CREATED,
    summary="上传补充材料",
    description=(
        "接收一个或多个文件，保存后自动执行 OCR 抽取与 AI 分类，材料状态置为已抽取。"
        "AI 预审由前端在材料就绪后调用 /report/generate 触发，以呈现「材料检查→AI 预审」分阶段流转。"
    ),
)
async def upload_materials(
    app: Application = Depends(get_application_or_404),
    files: list[UploadFile] = File(..., description="待上传的材料文件"),
    db: Session = Depends(get_db),
) -> list[MaterialRead]:
    max_bytes = config.MAX_UPLOAD_SIZE_MB * 1024 * 1024
    pending: list[tuple[str, bytes]] = []

    for file in files:
        filename = Path(file.filename or "unnamed").name
        if Path(filename).suffix.lower() not in ALLOWED_SUFFIXES:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"不支持的文件格式：{filename}",
            )
        content = await file.read()
        if len(content) > max_bytes:
            raise HTTPException(
                status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                detail=f"{filename} 超过 {config.MAX_UPLOAD_SIZE_MB}MB",
            )
        pending.append((filename, content))

    upload_root = Path(config.UPLOAD_DIR) / app.app_no
    upload_root.mkdir(parents=True, exist_ok=True)

    materials: list[Material] = []
    for filename, content in pending:
        stored_name = f"{uuid.uuid4().hex}_{filename}"
        file_url = f"{config.UPLOAD_DIR}/{app.app_no}/{stored_name}".replace("\\", "/")
        (upload_root / stored_name).write_bytes(content)
        material = Material(
            app_id=app.id,
            category="other",
            file_name=filename,
            file_url=file_url,
            file_size=len(content),
            version="v1.0",
            status=MaterialStatus.PENDING,
        )
        db.add(material)
        db.flush()

        # 上传后自动执行 AI 分类并回写类别、置信度与依据
        payload = MaterialClassifyInput(
            file_name=filename,
            mime_type=SUFFIX_MIME[Path(filename).suffix.lower()],
            file_path=file_url,
        )
        result, text = classify_material(payload, material.id)
        top = result.candidate
        material.category = top.category.value
        material.confidence = Decimal(str(top.confidence))
        material.reason = result.reason
        # OCR 文本随材料落库，供预审与重新分类复用，避免重复识别
        material.ocr_text = text or None
        # 分类完成即视为抽取完成
        material.status = MaterialStatus.OK
        materials.append(material)

    db.commit()
    for material in materials:
        db.refresh(material)
    return materials


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
    material = db.scalar(
        select(Material).where(Material.id == material_id, Material.app_id == app.id)
    )
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
    # 材料文件不变，优先复用库中已存 OCR 文本，避免重复识别
    result, text = classify_material(payload, material.id, text=material.ocr_text)
    top = result.candidate
    material.category = top.category.value
    material.confidence = Decimal(str(top.confidence))
    material.reason = result.reason
    material.ocr_text = text or material.ocr_text
    # 分类完成即视为抽取完成
    material.status = MaterialStatus.OK
    db.commit()
    db.refresh(material)

    # 重新分类后同步刷新 AI 预审报告
    all_materials = db.scalars(
        select(Material).where(Material.app_id == app.id).order_by(Material.id.asc())
    ).all()
    generate_report(db, app, all_materials)
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
    material = db.scalar(
        select(Material).where(Material.id == material_id, Material.app_id == app.id)
    )
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="材料不存在")

    material.category = payload.category.value
    db.commit()
    db.refresh(material)
    return material


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
    material = db.scalar(
        select(Material).where(Material.id == material_id, Material.app_id == app.id)
    )
    if material is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="材料不存在")

    file_url = material.file_url
    db.delete(material)
    db.commit()

    # 材料变化后重新执行 AI 预审：缺件时申请回到「待补件」
    remaining = db.scalars(
        select(Material).where(Material.app_id == app.id).order_by(Material.id)
    ).all()
    generate_report(db, app, remaining)

    if file_url:
        file_path = Path(file_url)
        if file_path.is_file():
            file_path.unlink()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
