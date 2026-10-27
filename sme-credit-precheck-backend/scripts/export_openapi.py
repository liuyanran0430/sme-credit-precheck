"""导出 OpenAPI 契约，供前端生成接口类型或做契约比对。

用法：
    python scripts/export_openapi.py
"""

import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.main import app  # noqa: E402


def main() -> None:
    output = ROOT / "openapi.json"
    output.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"OpenAPI 契约已导出：{output}")


if __name__ == "__main__":
    main()
