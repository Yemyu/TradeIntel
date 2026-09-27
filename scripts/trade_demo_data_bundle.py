"""Create and verify the current generic trade-report data supplement.

The bundle contains only published processed data, their manifests, and the
Chinese search index. It does not contain source ZIPs, API credentials, MySQL
data, or application code.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

ROOT = Path(__file__).resolve().parents[1]
BUNDLE_VERSION = "trade-demo-data-bundle-1"
FIXED_FILES = {
    "data/processed/trade_hts10/manifest.json",
    "data/processed/trade_scheduleb10/manifest.json",
    "data/processed/trade_classification/manifest.json",
    "data/processed/trade_classification/zh_hs4_2026.json",
}
IMPORT_FILE = re.compile(r"data/processed/trade_hts10/monthly/trade_hts10_20\d{2}_(0[1-9]|1[0-2])\.csv")
EXPORT_FILE = re.compile(
    r"data/processed/trade_scheduleb10/monthly/export_scheduleb10_20\d{2}_(0[1-9]|1[0-2])_[0-9a-f]{12}\.csv"
)
CLASSIFICATION_FILE = re.compile(
    r"data/processed/trade_classification/monthly/(?:import|export)_20\d{2}-(?:0[1-9]|1[0-2])_[0-9a-f]{12}\.json\.gz"
)


class BundleError(ValueError):
    pass


def _digest(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(chunk)
    return result.hexdigest()


def _json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise BundleError(f"清单缺失或 JSON 无效：{path}") from exc
    if not isinstance(value, dict):
        raise BundleError(f"清单必须是 JSON 对象：{path}")
    return value


def _inside(root: Path, relative: str) -> Path:
    rel = Path(relative)
    if rel.is_absolute() or ".." in rel.parts:
        raise BundleError(f"路径不允许离开数据包：{relative}")
    candidate = root / rel
    if candidate.is_symlink():
        raise BundleError(f"数据包不接受符号链接：{relative}")
    path = candidate.resolve()
    if not path.is_relative_to(root.resolve()):
        raise BundleError(f"路径不允许离开数据包：{relative}")
    return path


def _published_files(root: Path) -> tuple[list[str], dict[str, str]]:
    """Return the exact allowlisted paths and the two official data versions."""
    from tradeintel_ai.trade_data_repository import TradeDataRepository
    from tradeintel_ai.trade_export_repository import ExportDataRepository
    from tradeintel_ai.trade_classification_catalog import CATALOG_DIR, ClassificationCatalog

    root = root.resolve()
    import_catalog = TradeDataRepository(root).catalog()
    export_catalog = ExportDataRepository(root).catalog()
    classification = ClassificationCatalog(root)
    import_months = [item for item in import_catalog["months"]
                     if item["status"] == "queryable_aggregate"]
    export_months = [item for item in export_catalog["months"]
                     if item["status"] == "queryable_aggregate"]
    if len(import_months) != 48 or len(export_months) != 12:
        raise BundleError(
            f"当前数据版本与本次收口范围不符：进口 {len(import_months)} 月、出口 {len(export_months)} 月"
        )

    relatives = set(FIXED_FILES)
    for item in import_months:
        relative = item.get("processed_file")
        if not isinstance(relative, str) or not IMPORT_FILE.fullmatch(relative):
            raise BundleError("进口清单包含未预期的加工文件路径")
        relatives.add(relative)
    for item in export_months:
        relative = item.get("processed_file")
        if not isinstance(relative, str) or not EXPORT_FILE.fullmatch(relative):
            raise BundleError("出口清单包含未预期的加工文件路径")
        relatives.add(relative)

    class_manifest = _json(root / "data/processed/trade_classification/manifest.json")
    if class_manifest.get("dataset_versions") != {
            "import": import_catalog["dataset_version"],
            "export": export_catalog["dataset_version"]}:
        raise BundleError("商品目录与进口/出口数据版本不一致")
    class_months = class_manifest.get("months")
    if not isinstance(class_months, list) or len(class_months) != 60:
        raise BundleError("商品目录必须包含进口48月和出口12月")
    for item in class_months:
        if not isinstance(item, dict):
            raise BundleError("商品目录月份记录无效")
        relative = item.get("path")
        if not isinstance(relative, str) or not CLASSIFICATION_FILE.fullmatch(relative):
            raise BundleError("商品目录包含未预期的索引文件路径")
        classification.month(item.get("flow"), item.get("month"))
        relatives.add(relative)

    if len(relatives) != 124:
        raise BundleError(f"数据包清单应为124个文件，实际得到 {len(relatives)}")
    for relative in relatives:
        path = _inside(root, relative)
        if not path.is_file() or path.stat().st_size <= 0:
            raise BundleError(f"数据包文件缺失或为空：{relative}")
    versions = {"import": import_catalog["dataset_version"],
                "export": export_catalog["dataset_version"],
                "classification": classification.version}
    return sorted(relatives), versions


def _artifact_rows(root: Path, relatives: list[str]) -> list[dict[str, object]]:
    rows = []
    for relative in relatives:
        path = _inside(root, relative)
        rows.append({"path": relative, "bytes": path.stat().st_size,
                     "sha256": _digest(path)})
    return rows


def verify(root: Path) -> dict[str, object]:
    root = root.resolve()
    manifest_path = root / "BUNDLE_MANIFEST.json"
    manifest = _json(manifest_path)
    if manifest.get("version") != BUNDLE_VERSION:
        raise BundleError("数据包版本不受支持")
    files = manifest.get("files")
    if not isinstance(files, list) or len(files) != 124:
        raise BundleError("数据包文件清单必须恰好包含124个文件")
    seen: set[str] = set()
    for item in files:
        if not isinstance(item, dict):
            raise BundleError("数据包文件清单格式无效")
        relative = item.get("path")
        expected_bytes, expected_hash = item.get("bytes"), item.get("sha256")
        if (not isinstance(relative, str) or relative in seen
                or not (relative in FIXED_FILES or IMPORT_FILE.fullmatch(relative)
                        or EXPORT_FILE.fullmatch(relative) or CLASSIFICATION_FILE.fullmatch(relative))
                or type(expected_bytes) is not int or expected_bytes <= 0
                or not isinstance(expected_hash, str)
                or not re.fullmatch(r"[0-9a-f]{64}", expected_hash)):
            raise BundleError("数据包包含重复、越界或无效的文件记录")
        seen.add(relative)
        path = _inside(root, relative)
        if not path.is_file():
            raise BundleError(f"数据包文件缺失：{relative}")
        if path.stat().st_size != expected_bytes or _digest(path) != expected_hash:
            raise BundleError(f"数据包文件与 SHA-256 清单不一致：{relative}")

    expected, versions = _published_files(root)
    if seen != set(expected):
        raise BundleError("数据包内容与当前发布清单不一致")
    if manifest.get("dataset_versions") != versions:
        raise BundleError("数据包中的数据版本与内容不一致")
    return {"status": "verified", "file_count": len(seen),
            "total_bytes": sum(int(row["bytes"]) for row in files),
            "dataset_versions": versions, "network_calls": 0,
            "api_calls": 0, "mysql_required": False}


def create(output: Path, *, root: Path = ROOT) -> dict[str, object]:
    root = root.resolve()
    output = output.expanduser().resolve()
    if output.exists():
        raise BundleError(f"目标已存在，拒绝覆盖：{output}")
    relatives, versions = _published_files(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}.partial-", dir=output.parent))
    try:
        rows = []
        for relative in relatives:
            source = _inside(root, relative)
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            rows.append({"path": relative, "bytes": target.stat().st_size,
                         "sha256": _digest(target)})
        bundle_manifest = {
            "version": BUNDLE_VERSION,
            "created_at_utc": datetime.now(timezone.utc).isoformat(),
            "dataset_versions": versions,
            "files": rows,
            "excluded": ["raw Census ZIP archives", "API keys and .local configuration",
                         "MySQL database files", "temporary runs", "application source"],
            "network_calls": 0,
            "api_calls": 0,
        }
        (staging / "BUNDLE_MANIFEST.json").write_text(
            json.dumps(bundle_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        (staging / "BUNDLE_README.zh-CN.md").write_text(
            "# TradeShock 商品贸易演示数据\n\n"
            "这里有清单所列月份的美国进口、出口加工数据和商品名称索引，不只包含演示用的小麦。"
            "数据包不含项目源码、原始 Census ZIP、模型密钥或 MySQL 数据。\n\n"
            "请在项目根目录将整个 ZIP 解到一个**新的独立目录**，例如 `.local/trade-data-bundle-1/`。"
            "不要把 `data/` 合并到代码目录，也不要覆盖旧数据包。解压后先核验，再启动本地页面：\n\n"
            "```sh\n"
            "PYTHONPATH=src:. .venv/bin/python scripts/trade_demo_data_bundle.py verify --root .local/trade-data-bundle-1\n"
            ".venv/bin/python scripts/run_web.py --trade-data-root .local/trade-data-bundle-1\n"
            "```\n\n"
            "参数指向同时包含 `BUNDLE_MANIFEST.json` 和 `data/` 的目录，不是内层 `data/`。"
            "清单记录124个数据文件的大小与SHA-256；只有返回 `status: verified` 才继续。"
            "核验不下载数据，也不调用模型或 MySQL。数据包本身不是完整应用，政策案例数据不在包内。"
            "更完整的本地安装说明见代码仓库的 `docs/LOCAL_RUN.zh-CN.md`。\n",
            encoding="utf-8")
        checked = verify(staging)
        if output.exists():
            raise BundleError(f"目标在生成期间被创建，拒绝覆盖：{output}")
        # Reserve the final path without replacing an existing item, then move
        # each completed top-level item into that newly created directory.
        output.mkdir(parents=False, exist_ok=False)
        for name in ("data", "BUNDLE_MANIFEST.json", "BUNDLE_README.zh-CN.md"):
            os.rename(staging / name, output / name)
        staging.rmdir()
        return {**checked, "status": "created_and_verified", "output": str(output)}
    except Exception:
        # Only remove this unique staging directory created by this invocation.
        shutil.rmtree(staging, ignore_errors=True)
        raise


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create_parser = subparsers.add_parser("create", help="导出数据补充包，不覆盖已有目录")
    create_parser.add_argument("--output", type=Path, required=True)
    create_parser.add_argument("--source-root", type=Path, default=ROOT)
    verify_parser = subparsers.add_parser("verify", help="只读核验数据包及三个数据版本")
    verify_parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args(argv)
    try:
        result = (create(args.output, root=args.source_root) if args.command == "create"
                  else verify(args.root))
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(json.dumps({"status": "failed", "error": str(exc)},
                         ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
