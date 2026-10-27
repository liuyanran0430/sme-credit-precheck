"""OCR / 字段抽取服务（业务逻辑待实现）。"""

from app.schemas.ai_classification import MaterialClassifyInput, OcrResult


def extract_fields(payload: MaterialClassifyInput) -> OcrResult:
    """从材料文件中抽取结构化字段及字段置信度。

    待实现要点：
    1. PDF 文本层优先，扫描件走 OCR；
    2. 按材料类别输出对应字段（企业名称、信用代码、法人、注册资本等）；
    3. 每个字段返回独立置信度，供低置信项识别使用。
    """
    raise NotImplementedError("字段抽取逻辑待实现")
