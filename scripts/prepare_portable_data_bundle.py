"""Copy the four verified non-Git data artifacts into a portable folder.

The output is an ordinary directory, deliberately not a zip archive. It can
be copied into a prepared checkout, then checked with
``scripts/verify_portable_data.py --root <checkout>``. It never includes
provider configuration, the Git repository, raw Census ZIP archives, or any
file outside the fixed manifest.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil

try:
    from scripts.verify_portable_data import ROOT, _digest, verify
except ModuleNotFoundError:  # direct invocation: python scripts/prepare_...
    from verify_portable_data import ROOT, _digest, verify


def prepare(output: Path, *, root: Path = ROOT) -> dict:
    root = root.resolve()
    output = output.resolve()
    if output.exists():
        raise ValueError(f"output already exists; refusing to overwrite: {output}")
    manifest = root / "data/PORTABLE_DATA_MANIFEST.json"
    report = verify(root=root, manifest_path=manifest)
    if report["status"] != "ready":
        raise ValueError("portable data are incomplete; run verify_portable_data.py first")
    definition = json.loads(manifest.read_text(encoding="utf-8"))
    output.mkdir(parents=True)
    copied = []
    for item in definition["artifacts"]:
        relative = Path(item["path"])
        source = root / relative
        target = output / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append({"id": item["id"], "path": relative.as_posix(),
                       "bytes": target.stat().st_size, "sha256": _digest(target)})
    manifest_target = output / "data/PORTABLE_DATA_MANIFEST.json"
    manifest_target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(manifest, manifest_target)
    readme = output / "BUNDLE_README.zh-CN.md"
    readme.write_text(
        "# TradeShock 配套数据文件夹\n\n"
        "本文件夹只包含四个被普通 Git clone 忽略、但严格离线演示需要的文件。"
        "它不是完整源代码或压缩包，不包含 API 配置、MySQL密码、原始 Census ZIP 或临时运行记录。\n\n"
        "将其中的 `data/` 合并到已准备好的 TradeShock 项目根目录，再运行：\n\n"
        "```bash\n"
        ".venv/bin/python scripts/verify_portable_data.py\n"
        "```\n\n"
        "只有输出 `status: ready` 才表示四个文件的大小与 SHA-256 一致。"
        "核验命令只读，不自动下载或替换文件。这个数据包不能单独运行项目；源码和requirements仍需通过仓库取得。\n",
        encoding="utf-8")
    bundle_manifest = {
        "version": "portable-data-bundle-1",
        "created_at_utc": datetime.now(timezone.utc).isoformat(),
        "source_manifest": "data/PORTABLE_DATA_MANIFEST.json",
        "files": copied,
        "included": "four fixed portable-data-manifest-1 artifacts plus the manifest",
        "excluded": ["provider configuration", "API keys", "MySQL credentials",
                     "raw Census ZIP archives", "Git repository", "tmp run records"],
        "network_calls": 0,
    }
    (output / "BUNDLE_MANIFEST.json").write_text(
        json.dumps(bundle_manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {"status": "created", "output": str(output), "file_count": len(copied),
            "bytes": sum(row["bytes"] for row in copied), "network_calls": 0}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True,
                        help="new output folder; existing paths are rejected")
    args = parser.parse_args(argv)
    try:
        result = prepare(args.output)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "bundle_failed", "error": str(exc)},
                         ensure_ascii=False, indent=2))
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
