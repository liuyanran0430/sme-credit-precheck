"""知识库向量索引重建脚本（阶段二）。

读取 `knowledge_base/` 下的 Markdown 与 YAML，按标题/规则条目分块，
调用 embedding 后写入 `app/rag/` 的四个 collection：

    kb_policy           01_信贷政策/**/*.md
    kb_material_review  02_材料审核标准/**/*.md
    kb_rule_config      03_规则配置/**/*.yaml
    kb_cases            04_案例与FAQ/**/*.md

注意：
- Embedding 依赖后端配置 `EMBEDDING_MODEL`；未配置时会写入零向量占位，
  检索结果无意义，仅用于结构自检；
- `VECTOR_STORE_BACKEND=memory` 是进程内存储，脚本退出后索引即丢失，
  生产请设置 `VECTOR_STORE_BACKEND=chroma` 并安装 chromadb；
- `VECTOR_STORE_PERSIST_DIR` 为相对路径时，按后端目录解析，与后端服务保持一致。

用法（项目根目录执行）：
    python scripts/rebuild_vector_index.py --dry-run
    python scripts/rebuild_vector_index.py
    python scripts/rebuild_vector_index.py --reset
    python scripts/rebuild_vector_index.py --collection kb_policy --batch-size 8

退出码：0=成功，1=失败。
"""

from __future__ import annotations

import argparse
import logging
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT_DIR = Path(__file__).resolve().parents[1]
DEFAULT_KB_DIR = ROOT_DIR / "knowledge_base"
BACKEND_DIR = ROOT_DIR / "sme-credit-precheck-backend"

COLLECTIONS = {
    "kb_policy": "01_信贷政策",
    "kb_material_review": "02_材料审核标准",
    "kb_rule_config": "03_规则配置",
    "kb_cases": "04_案例与FAQ",
}

PRODUCT_CODES = {
    "普惠小微经营贷": "AP",
    "小微快贷": "AK",
    "经营性抵押贷": "AJ",
    "科技e贷": "AE",
}

CATEGORY_KEYWORDS = {
    "营业执照": "business_license",
    "银行流水": "bank_statement",
    "财务报表": "financial_report",
    "纳税申报表": "tax_return",
    "征信授权书": "credit_auth",
    "其他材料": "other",
}

RULE_ID_PATTERN = re.compile(r"[A-Z]{2}-[HS]\d{2}")
CHECK_ID_PATTERN = re.compile(r"C\d+")
MAX_MARKDOWN_CHARS = 600

logger = logging.getLogger("rebuild_vector_index")


@dataclass
class Chunk:
    """待入库的知识块（向量在入库前补齐）。"""

    collection: str
    id: str
    text: str
    metadata: dict[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------- Markdown 分块


def _split_markdown_blocks(text: str) -> list[tuple[str, str]]:
    """按二级标题切分 Markdown，返回 (section, body) 列表。"""
    blocks: list[tuple[str, list[str]]] = []
    section = ""
    current: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current:
                blocks.append((section, current))
            section = line.lstrip("# ").strip()
            current = []
        elif line.startswith("# ") and not section:
            section = line.lstrip("# ").strip()
        else:
            current.append(line)
    if current:
        blocks.append((section, current))
    return [(name, "\n".join(lines).strip()) for name, lines in blocks if "\n".join(lines).strip()]


def _split_long_body(body: str, max_chars: int) -> list[str]:
    """长段落按空行分组，再按长度上限合并。"""
    if len(body) <= max_chars:
        return [body]
    paragraphs = [p.strip() for p in re.split(r"\n\s*\n", body) if p.strip()]
    parts: list[str] = []
    buffer = ""
    for paragraph in paragraphs:
        if not buffer:
            buffer = paragraph
        elif len(buffer) + 2 + len(paragraph) <= max_chars:
            buffer = f"{buffer}\n\n{paragraph}"
        else:
            parts.append(buffer)
            buffer = paragraph
    if buffer:
        parts.append(buffer)

    # 单段仍超长时按行硬切
    result: list[str] = []
    for part in parts:
        if len(part) <= max_chars:
            result.append(part)
            continue
        for start in range(0, len(part), max_chars):
            result.append(part[start : start + max_chars])
    return result


def _detect_product(*texts: str) -> str:
    for text in texts:
        for product in PRODUCT_CODES:
            if product in text:
                return product
    return ""


def _detect_category(file_name: str) -> str:
    for keyword, category in CATEGORY_KEYWORDS.items():
        if keyword in file_name:
            return category
    return ""


def _markdown_chunks(
    path: Path,
    kb_dir: Path,
    collection: str,
) -> list[Chunk]:
    rel = path.relative_to(kb_dir).as_posix()
    text = path.read_text(encoding="utf-8")
    file_name = path.stem

    base_meta: dict[str, Any] = {"source": rel}
    if collection == "kb_policy":
        product = _detect_product(file_name, text)
        base_meta["product"] = product
        base_meta["product_code"] = PRODUCT_CODES.get(product, "")
    elif collection == "kb_material_review":
        base_meta["category"] = _detect_category(file_name)
        checks = sorted(set(CHECK_ID_PATTERN.findall(text)))
        base_meta["check_item"] = ",".join(checks)
    elif collection == "kb_cases":
        base_meta["case_type"] = "faq" if "常见问题" in file_name else "exception"
        base_meta["product"] = _detect_product(file_name, text)

    chunks: list[Chunk] = []
    for index, (section, body) in enumerate(_split_markdown_blocks(text)):
        for part_index, part in enumerate(_split_long_body(body, MAX_MARKDOWN_CHARS)):
            chunk_text = f"{section}\n\n{part}" if section else part
            meta = dict(base_meta)
            meta["section"] = section
            rule_ids = sorted(set(RULE_ID_PATTERN.findall(chunk_text)))
            meta["rule_id"] = ",".join(rule_ids)
            meta["kind"] = (
                "hard" if any("-H" in rid for rid in rule_ids) else ("soft" if rule_ids else "")
            )
            chunks.append(
                Chunk(
                    collection=collection,
                    id=f"{rel}#{index}-{part_index}",
                    text=chunk_text,
                    metadata=meta,
                )
            )
    return chunks


# ---------------------------------------------------------------- YAML 分块


def _value_text(value: Any) -> str:
    if isinstance(value, list):
        return "、".join(str(item) for item in value)
    return str(value)


def _rule_chunks(path: Path, kb_dir: Path) -> list[Chunk]:
    rel = path.relative_to(kb_dir).as_posix()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []

    product = str(data.get("product") or "")
    code = str(data.get("product_code") or "")
    version = str(data.get("version") or "")
    base_meta = {
        "source": rel,
        "product": product,
        "product_code": code,
        "version": version,
    }

    chunks: list[Chunk] = []
    for index, rule in enumerate(data.get("rules") or []):
        if not isinstance(rule, dict):
            continue
        rule_id = str(rule.get("rule_id") or "")
        sources = rule.get("source")
        text = (
            f"规则 {rule_id}（{rule.get('rule_name') or ''}）\n"
            f"产品：{product}（{code}）\n"
            f"类型：{rule.get('kind') or ''}（hard=强规则直接拒绝，soft=弱规则影响评分）\n"
            f"证据来源：{_value_text(sources)}\n"
            f"判定条件：{rule.get('field') or ''} {rule.get('operator') or ''} "
            f"{_value_text(rule.get('value'))}\n"
            f"业务说明：{rule.get('detail_zh') or ''}"
        )
        meta = dict(base_meta)
        meta["rule_id"] = rule_id
        meta["kind"] = str(rule.get("kind") or "")
        chunks.append(
            Chunk(collection="kb_rule_config", id=f"{rel}#rule-{index}", text=text, metadata=meta)
        )

    scoring = data.get("scoring")
    if isinstance(scoring, dict):
        chunks.append(
            Chunk(
                collection="kb_rule_config",
                id=f"{rel}#scoring",
                text=(
                    f"{product}（{code}）评分规则\n"
                    f"强规则失败是否直接拒绝：{scoring.get('hard_rules_reject')}\n"
                    f"基础分：{scoring.get('base_score')}；每条弱规则得分：{scoring.get('soft_rule_score')}\n"
                    f"等级阈值：{_value_text(scoring.get('level_thresholds'))}"
                ),
                metadata={**base_meta, "rule_id": "", "kind": ""},
            )
        )

    logic = data.get("conclusion_logic")
    if isinstance(logic, dict):
        chunks.append(
            Chunk(
                collection="kb_rule_config",
                id=f"{rel}#conclusion",
                text=(
                    f"{product}（{code}）结论口径\n" + "\n".join(
                        f"{key}：{value}" for key, value in logic.items()
                    )
                ),
                metadata={**base_meta, "rule_id": "", "kind": ""},
            )
        )
    return chunks


def _scoring_chunks(path: Path, kb_dir: Path) -> list[Chunk]:
    rel = path.relative_to(kb_dir).as_posix()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    version = str(data.get("version") or "")
    chunks: list[Chunk] = []
    for code, item in (data.get("products") or {}).items():
        if not isinstance(item, dict):
            continue
        product = next((p for p, c in PRODUCT_CODES.items() if c == code), "")
        text = (
            f"产品 {product}（{code}）评分参数\n"
            f"基础分 {item.get('base_score')}，每条弱规则 {item.get('soft_rule_score')} 分，"
            f"弱规则 {item.get('soft_rule_count')} 条，满分 {item.get('full_score')}"
        )
        chunks.append(
            Chunk(
                collection="kb_rule_config",
                id=f"{rel}#{code}",
                text=text,
                metadata={
                    "source": rel,
                    "product": product,
                    "product_code": code,
                    "version": version,
                    "rule_id": "",
                    "kind": "",
                },
            )
        )
    return chunks


def _conclusion_chunks(path: Path, kb_dir: Path) -> list[Chunk]:
    rel = path.relative_to(kb_dir).as_posix()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    version = str(data.get("version") or "")
    base = {"source": rel, "version": version, "product": "", "rule_id": "", "kind": ""}
    chunks: list[Chunk] = []

    for index, item in enumerate(data.get("conclusions") or []):
        if not isinstance(item, dict):
            continue
        chunks.append(
            Chunk(
                collection="kb_rule_config",
                id=f"{rel}#conclusion-{index}",
                text=(
                    f"结论 {item.get('code')}（{item.get('label')}，优先级 {item.get('priority')}）："
                    f"{item.get('description')}"
                ),
                metadata=dict(base),
            )
        )
    for index, item in enumerate(data.get("logic") or []):
        if not isinstance(item, dict):
            continue
        chunks.append(
            Chunk(
                collection="kb_rule_config",
                id=f"{rel}#logic-{index}",
                text=(
                    f"结论判定：{item.get('conclusion')}\n"
                    f"条件：{item.get('condition')}\n说明：{item.get('detail')}"
                ),
                metadata=dict(base),
            )
        )
    for key, value in (data.get("supplement_source") or {}).items():
        if isinstance(value, dict):
            chunks.append(
                Chunk(
                    collection="kb_rule_config",
                    id=f"{rel}#supplement-{key}",
                    text=(
                        f"补件来源 {key}：{value.get('label')}；补齐后回流至 {value.get('after_supplement')}"
                    ),
                    metadata=dict(base),
                )
            )
    return chunks


def _consistency_chunks(path: Path, kb_dir: Path) -> list[Chunk]:
    rel = path.relative_to(kb_dir).as_posix()
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        return []
    version = str(data.get("version") or "")
    base = {"source": rel, "version": version, "product": "", "rule_id": "", "kind": ""}
    chunks: list[Chunk] = []
    for index, item in enumerate(data.get("checks") or []):
        if not isinstance(item, dict):
            continue
        check_id = str(item.get("check_id") or "")
        chunks.append(
            Chunk(
                collection="kb_rule_config",
                id=f"{rel}#check-{index}",
                text=(
                    f"一致性校验 {check_id}：{item.get('check_item')}\n"
                    f"严重度：{item.get('severity')}\n"
                    f"比对来源：{_value_text(item.get('sources'))}；字段：{item.get('field')}\n"
                    f"判定逻辑：{item.get('logic')}\n"
                    f"不一致处置：{item.get('fail_suggestion')}\n"
                    f"无法判定条件：{item.get('uncertain_condition')}"
                ),
                metadata={**base, "check_item": check_id},
            )
        )
    return chunks


def _yaml_chunks(path: Path, kb_dir: Path) -> list[Chunk]:
    name = path.name
    if name.startswith("rule_"):
        return _rule_chunks(path, kb_dir)
    if name == "评分配置.yaml":
        return _scoring_chunks(path, kb_dir)
    if name == "结论口径.yaml":
        return _conclusion_chunks(path, kb_dir)
    if name == "一致性校验规则.yaml":
        return _consistency_chunks(path, kb_dir)
    return []


# ---------------------------------------------------------------- 采集与入库


def collect_chunks(kb_dir: Path) -> dict[str, list[Chunk]]:
    """按 collection 收集全部知识块。"""
    grouped: dict[str, list[Chunk]] = {name: [] for name in COLLECTIONS}
    for collection, rel_dir in COLLECTIONS.items():
        root = kb_dir / rel_dir
        if not root.is_dir():
            logger.warning("知识库目录不存在，已跳过：%s", root)
            continue
        if collection == "kb_rule_config":
            for path in sorted(root.rglob("*.yaml")):
                grouped[collection].extend(_yaml_chunks(path, kb_dir))
        else:
            for path in sorted(root.rglob("*.md")):
                grouped[collection].extend(_markdown_chunks(path, kb_dir, collection))
    return grouped


def _resolve_persist_dir() -> str:
    """把相对持久化目录解析到后端目录，避免受脚本执行目录影响。"""
    from app.core import config  # noqa: PLC0415

    persist_dir = Path(config.VECTOR_STORE_PERSIST_DIR)
    if not persist_dir.is_absolute():
        persist_dir = BACKEND_DIR / persist_dir
    config.VECTOR_STORE_PERSIST_DIR = str(persist_dir)
    return str(persist_dir)


def run(args: argparse.Namespace) -> int:
    if str(BACKEND_DIR) not in sys.path:
        sys.path.insert(0, str(BACKEND_DIR))

    from app.core import config  # noqa: PLC0415

    kb_dir = Path(args.kb_dir)
    if not kb_dir.is_dir():
        print(f"[ERROR] 知识库目录不存在：{kb_dir}", file=sys.stderr)
        return 1

    grouped = collect_chunks(kb_dir)
    selected = (
        {args.collection: grouped.get(args.collection, [])}
        if args.collection
        else grouped
    )
    if args.collection and args.collection not in COLLECTIONS:
        print(
            f"[ERROR] 未知 collection：{args.collection}，可选：{', '.join(COLLECTIONS)}",
            file=sys.stderr,
        )
        return 1

    total = sum(len(chunks) for chunks in selected.values())
    for collection, chunks in selected.items():
        print(f"[CHUNK] {collection}: {len(chunks)} 块")
        if args.dry_run:
            for chunk in chunks[:2]:
                preview = chunk.text.replace("\n", " / ")[:80]
                print(f"        示例 {chunk.id}: {preview}…")
    if total == 0:
        print("[ERROR] 未生成任何知识块", file=sys.stderr)
        return 1
    if args.dry_run:
        print("-" * 60)
        print(f"dry-run 完成：共 {total} 块，未调用 embedding、未写入向量库")
        return 0

    if not config.EMBEDDING_MODEL:
        print(
            "[WARN] EMBEDDING_MODEL 未配置，将写入零向量占位；检索结果无意义，"
            "请在 .env 中配置后可用的 embedding 模型后重跑。",
            file=sys.stderr,
        )
    if config.VECTOR_STORE_BACKEND.lower() == "memory":
        print(
            "[WARN] VECTOR_STORE_BACKEND=memory 为进程内存储，脚本退出后索引丢失；"
            "生产请改用 chroma。",
            file=sys.stderr,
        )

    persist_dir = _resolve_persist_dir()
    from app.llm import get_embedding_client  # noqa: PLC0415
    from app.rag import Document, get_vector_store  # noqa: PLC0415

    store = get_vector_store()
    client = get_embedding_client()

    if args.reset:
        for collection in selected:
            try:
                store.reset_collection(collection)
                print(f"[RESET] {collection}")
            except Exception as exc:  # noqa: BLE001 — 不存在的 collection 可忽略
                logger.warning("清空 collection 失败 %s：%s", collection, exc)

    for collection, chunks in selected.items():
        if not chunks:
            continue
        vectors: list[list[float]] = []
        for start in range(0, len(chunks), args.batch_size):
            batch = chunks[start : start + args.batch_size]
            vectors.extend(client.embed([chunk.text for chunk in batch]))
        if len(vectors) != len(chunks):
            print(
                f"[ERROR] {collection} embedding 数量不匹配：{len(vectors)} != {len(chunks)}",
                file=sys.stderr,
            )
            return 1
        documents = [
            Document(
                id=chunk.id,
                text=chunk.text,
                vector=vector,
                metadata=chunk.metadata,
            )
            for chunk, vector in zip(chunks, vectors)
        ]
        store.upsert(documents, collection=collection)
        print(f"[UPSERT] {collection}: {len(documents)} 条")

    print("-" * 60)
    print(f"索引重建完成：backend={config.VECTOR_STORE_BACKEND}，persist_dir={persist_dir}")
    try:
        stats = store.get_collection_stats()
        print(f"collection 统计：{stats}")
    except NotImplementedError:
        pass
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="重建知识库 RAG 向量索引")
    parser.add_argument("--kb-dir", default=str(DEFAULT_KB_DIR), help="知识库根目录")
    parser.add_argument("--dry-run", action="store_true", help="只分块统计，不调用 embedding/写库")
    parser.add_argument("--reset", action="store_true", help="入库前清空目标 collection")
    parser.add_argument("--collection", choices=sorted(COLLECTIONS), help="只重建指定 collection")
    parser.add_argument("--batch-size", type=int, default=16, help="embedding 批大小，默认 16")
    parser.add_argument("--verbose", action="store_true", help="输出 INFO 级日志")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(name)s: %(message)s",
    )

    try:
        return run(args)
    except ImportError as exc:
        print(f"[ERROR] 依赖或后端模块导入失败：{exc}", file=sys.stderr)
        return 1
    except Exception as exc:  # noqa: BLE001 — CLI 兜底，避免输出整段堆栈
        logger.exception("索引重建失败")
        print(f"[ERROR] 索引重建失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
