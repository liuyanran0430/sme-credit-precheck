"""基于 LangChain 的材料分类服务。

三步流程：
1. 文件名先验：提取关键词，作为 LLM 分类的参考提示；
2. OCR 文本加载：PDF 文本层优先，扫描件与图片走 RapidOCR；
3. 内容侧分类：LLM + 结构化输出（with_structured_output）。
"""

import io
import logging
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel, Field
from pathlib import Path

from app.schemas.ai_classification import (
    CATEGORY_LABELS,
    CategoryCandidate,
    LOW_CONFIDENCE_THRESHOLD,
    MaterialCategory,
    MaterialClassifyInput,
    MaterialClassifyResponse,
    MimeType,
)

logger = logging.getLogger(__name__)

# 项目根目录下的 .env 文件路径
_ENV_PATH = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(_ENV_PATH)


def _env(key: str, default: str | None = None) -> str | None:
    """从 .env / 环境变量读取配置，未设置时返回 default。"""
    return os.getenv(key, default)


def _env_int(key: str, default: int) -> int:
    value = _env(key)
    try:
        return int(value) if value is not None else default
    except ValueError:
        return default


# LLM 配置（直接从 .env 读取，不依赖 settings）
OPENAI_API_KEY = _env("OPENAI_API_KEY")
OPENAI_BASE_URL = _env("OPENAI_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL = _env("LLM_MODEL", "gpt-4o-mini")
LLM_TIMEOUT_SECONDS = _env_int("LLM_TIMEOUT_SECONDS", 60)

# OCR 配置
OCR_DPI = _env_int("OCR_DPI", 200)
OCR_MAX_PAGES = _env_int("OCR_MAX_PAGES", 10)
CLASSIFY_TEXT_MAX_CHARS = _env_int("CLASSIFY_TEXT_MAX_CHARS", 6000)

MODEL_VERSION = "cls-langchain-v1.0"

# 文件后缀 → MIME 类型映射
SUFFIX_MIME = {
    ".pdf": MimeType.PDF,
    ".jpg": MimeType.JPEG,
    ".jpeg": MimeType.JPEG,
    ".png": MimeType.PNG,
}

# 文件名关键词 → 类别先验（仅作参考，不直接决定结果）
FILENAME_HINTS: list[tuple[MaterialCategory, tuple[str, ...]]] = [
    (MaterialCategory.BUSINESS_LICENSE, ("营业执照", "执照", "license")),
    (MaterialCategory.BANK_STATEMENT, ("银行流水", "流水", "对账单", "statement")),
    (
        MaterialCategory.FINANCIAL_REPORT,
        ("财务报表", "资产负债表", "利润表", "现金流量表", "financial"),
    ),
    (MaterialCategory.TAX_RETURN, ("纳税", "申报表", "完税", "tax")),
    (MaterialCategory.CREDIT_AUTH, ("征信", "授权书", "credit")),
]

SYSTEM_PROMPT = """你是银行小微企业授信材料分类助手，请根据文件名与 OCR 文本将材料归入以下类别之一：
- business_license：营业执照
- bank_statement：银行流水（对公/个人账户流水、对账单）
- financial_report：财务报表（资产负债表、利润表、现金流量表等）
- tax_return：纳税申请表（纳税申报表、完税证明）
- credit_auth：征信授权书（征信查询授权、企业/个人征信授权）
- other：其他（无法判断或不属于上述类别）

判定要求：
1. 以 OCR 文本中的标题、表头、关键字段为主要依据，文件名仅作辅助参考；
2. 无法判断时归入 other，并在 reason 中说明原因；
3. confidence 表示分类把握程度，取值范围 0~1。

请严格以 JSON 格式输出，不要输出任何 JSON 以外的内容，字段如下：
{{"category": "类别编码（必须是上述 6 个之一）", "confidence": 0.0~1.0 的浮点数, "reason": "分类依据"}}"""


class LlmClassification(BaseModel):
    """LLM 结构化分类输出。"""

    category: MaterialCategory = Field(description="材料类别编码")
    confidence: float = Field(ge=0, le=1, description="分类置信度")
    reason: str = Field(description="分类依据，需引用文件名或 OCR 文本中的证据")


def filename_prior(file_name: str) -> CategoryCandidate | None:
    """第一步：从文件名提取关键词，生成先验类别。"""
    name = file_name.lower()
    for category, keywords in FILENAME_HINTS:
        if any(keyword in name for keyword in keywords):
            return CategoryCandidate(
                category=category,
                label=CATEGORY_LABELS[category],
                confidence=0.5,
            )
    return None


@lru_cache(maxsize=1)
def _ocr_engine():
    """RapidOCR 引擎（懒加载，避免启动时加载模型）。"""
    from rapidocr import RapidOCR

    return RapidOCR()


def _ocr_image(content: bytes) -> str:
    """对图片字节执行 OCR，失败时返回空文本。"""
    try:
        import numpy as np
        from PIL import Image

        image = Image.open(io.BytesIO(content)).convert("RGB")
        output = _ocr_engine()(np.array(image))

        # RapidOCR 3.x 返回带 txts 的对象，2.x 返回 (result, elapse) 元组
        texts = getattr(output, "txts", None)
        if texts:
            return "\n".join(texts)
        if isinstance(output, tuple) and output and output[0]:
            return "\n".join(item[1] for item in output[0])
        return ""
    except Exception as exc:  # noqa: BLE001 - OCR 失败不应中断分类
        logger.warning("图片 OCR 失败：%s", exc)
        return ""


def _read_source(payload: MaterialClassifyInput) -> bytes:
    if payload.file_content is not None:
        return payload.file_content
    if not payload.file_path:
        return ""
    path = Path(payload.file_path)
    if not path.is_absolute():
        path = Path.cwd() / path
    try:
        return path.read_bytes()
    except OSError as exc:
        logger.warning("读取材料文件失败：%s", exc)
        return ""


def _pdf_text(content: bytes) -> str:
    """PDF 文本层优先；无文本层的页面渲染后走 OCR。"""
    try:
        import pymupdf as fitz
    except ImportError:  # 兼容旧版 PyMuPDF
        try:
            import fitz
        except ImportError:
            logger.warning("未安装 PyMuPDF，无法读取 PDF 文本")
            return ""

    parts: list[str] = []
    try:
        with fitz.open(stream=content, filetype="pdf") as doc:
            page_count = min(len(doc), OCR_MAX_PAGES)
            for index in range(page_count):
                page = doc.load_page(index)
                text = page.get_text().strip()
                if text:
                    parts.append(text)
                else:
                    pixmap = page.get_pixmap(dpi=OCR_DPI)
                    parts.append(_ocr_image(pixmap.tobytes("png")))
    except Exception as exc:  # noqa: BLE001 - 解析失败降级为空文本
        logger.warning("PDF 文本解析失败：%s", exc)
    return "\n".join(part for part in parts if part)


def _extract_text(content: bytes, suffix: str) -> str:
    """按文件后缀抽取 OCR 文本（不截断，供落库与后续分析复用）。"""
    if suffix == ".pdf":
        text = _pdf_text(content)
    elif suffix in {".jpg", ".jpeg", ".png"}:
        text = _ocr_image(content)
    else:
        text = ""
    return text.strip()


def load_text(payload: MaterialClassifyInput) -> str:
    """第二步：加载 OCR 文本。"""
    content = _read_source(payload)
    if not content:
        return ""
    return _extract_text(content, Path(payload.file_name).suffix.lower())


@lru_cache(maxsize=1)
def _build_chain():
    """构建 LangChain 链：提示词 → LLM → 结构化输出。"""
    llm = ChatOpenAI(
        model=LLM_MODEL,
        api_key=OPENAI_API_KEY,
        base_url=OPENAI_BASE_URL,
        temperature=0,
        timeout=LLM_TIMEOUT_SECONDS,
    )
    prompt = ChatPromptTemplate.from_messages(
        [
            ("system", SYSTEM_PROMPT),
            ("human", "文件名：{file_name}\n文件名先验：{prior}\nOCR 文本：\n{text}"),
        ]
    )
    return prompt | llm.with_structured_output(LlmClassification, method="json_mode")


def classify_by_llm(
    file_name: str, prior: CategoryCandidate | None, text: str
) -> LlmClassification:
    """第三步：LLM 内容分类（结构化输出）。"""
    if not OPENAI_API_KEY:
        raise RuntimeError("未配置 OPENAI_API_KEY")
    prompt_text = (text or "（未识别到文本）")[:CLASSIFY_TEXT_MAX_CHARS]
    return _build_chain().invoke(
        {
            "file_name": file_name,
            "prior": f"{prior.label}（{prior.category.value}）" if prior else "无",
            "text": prompt_text,
        }
    )


def classify_material(
    payload: MaterialClassifyInput,
    material_id: int,
    text: str | None = None,
) -> tuple[MaterialClassifyResponse, str]:
    """对单个材料文件执行三步分类，返回分类结果与 OCR 文本。

    传入 text 时直接复用（如数据库已存 OCR 文本），不再重复识别。
    """
    prior = filename_prior(payload.file_name)
    if text is None:
        text = load_text(payload)

    try:
        result = classify_by_llm(payload.file_name, prior, text)
        category = result.category
        confidence = result.confidence
        reason = result.reason
        if prior and prior.category != category:
            reason = f"{reason}（文件名先验为{prior.label}，未采用）"
    except Exception as exc:  # noqa: BLE001 - LLM 不可用时降级兜底
        logger.warning("LLM 分类失败，使用兜底类别：%s", exc)
        category = prior.category if prior else MaterialCategory.OTHER
        confidence = 0.3
        reason = f"LLM 分类不可用（{str(exc)[:200]}），按文件名先验兜底"

    # 置信度低于阈值时归入其他，转人工分类
    if confidence < LOW_CONFIDENCE_THRESHOLD:
        reason = (
            f"{reason}（置信度 {confidence:.2f} 低于 {LOW_CONFIDENCE_THRESHOLD}，"
            f"原判为{CATEGORY_LABELS[category]}，归入其他转人工分类）"
        )
        category = MaterialCategory.OTHER

    response = MaterialClassifyResponse(
        material_id=material_id,
        candidate=CategoryCandidate(
            category=category,
            label=CATEGORY_LABELS[category],
            confidence=confidence,
        ),
        reason=reason,
        model_version=MODEL_VERSION,
    )
    return response, text


# def main() -> None:
#     """验证 classify_material 的完整三步分类链路。

#     默认读取项目根目录 samples/ 下的本地样例文件，对每个文件依次执行
#     文件名先验 → OCR 文本加载 → LLM 内容分类，并输出分类结果。
#     可通过命令行参数指定其他目录：python -m app.services.classifier <目录>
#     """
#     import sys

#     # 验证场景下屏蔽 httpx/LLM 的 INFO 日志，仅保留警告
#     logging.basicConfig(level=logging.WARNING, format="%(levelname)s: %(message)s")

#     sample_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else _ENV_PATH.parent / "samples"
#     files = [r'E:\AI全栈\【刘嫣然】F2小微企业授信智能预审系统项目材料\模拟数据\营业执照-1.jpeg']

#     print("=" * 70)
#     print(f"LLM 配置：base_url={OPENAI_BASE_URL}  model={LLM_MODEL}")
#     print(f"OPENAI_API_KEY={'***' + OPENAI_API_KEY[-6:] if OPENAI_API_KEY else '未配置'}")
#     print(f"（{len(files)} 个文件）")
#     print("=" * 70)

#     if not OPENAI_API_KEY:
#         print("⚠️  未配置 OPENAI_API_KEY，无法调用 LLM，请检查 .env 文件。")
#         return

#     for index, pathname in enumerate(files, start=1):
#         file_name = os.path.basename(pathname)
#         payload = MaterialClassifyInput(
#             file_name=file_name,
#             mime_type=SUFFIX_MIME[Path(file_name).suffix.lower()],
#             file_path=pathname,
#         )
#         prior = filename_prior(file_name)
#         result, _ = classify_material(payload, material_id=index)
#         top = result.candidate
#         print(f"\n📄 {file_name}")
#         print(f"   先验：{prior.label if prior else '无'}")
#         print(f"   预测类别：{top.category.value}（{top.label}）")
#         print(f"   置信度：{top.confidence:.2f}")
#         print(f"   模型版本：{result.model_version}")
#         print(f"   依据：{result.reason}")


# if __name__ == "__main__":
#     main()
