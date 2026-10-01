"""Build a local, explicit-source candidate ZIP; never publish it.

Run from the repository checkout. Tracked src/web files form the audited base
used by the old data-only candidate; the four new Agent modules are explicit.
No .local data, credentials, runs, course material or experiment packages enter.
"""
from __future__ import annotations

import argparse
import hashlib
import re
import stat
import subprocess
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo


ROOT = Path(__file__).resolve().parents[1]
EXTRA = (
    "src/tradeintel_ai/trade_agent.py",
    "src/tradeintel_ai/trade_agent_deepseek.py",
    "src/tradeintel_ai/trade_agent_store.py",
    "src/tradeintel_ai/trade_agent_tools.py",
)
REQUIRED = ("requirements.txt", "scripts/run_web.py",
            "scripts/trade_demo_data_bundle.py", *EXTRA)
README = ROOT / "docs/AGENT_REVIEWER_QUICKSTART.zh-CN.md"
DENIED = (".local/", "tmp/", "output/", "vendor/course-reference/",
          ".workbuddy/", "evals/", "docs/handoff/")
SECRET = (
    re.compile(rb"\bsk-[A-Za-z0-9_.-]{24,}\b"),
    re.compile(rb"\b[0-9a-f]{32}\.[A-Za-z0-9]{16}\b"),
    re.compile(rb"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
)


def _members() -> list[tuple[str, bytes]]:
    listed = subprocess.run(["git", "ls-files", "-z", "--", "src", "web"],
                            cwd=ROOT, check=True, capture_output=True).stdout
    names = {name.decode("utf-8") for name in listed.split(b"\0") if name}
    names.update(REQUIRED)
    members: list[tuple[str, bytes]] = [("README.md", README.read_bytes())]
    for name in sorted(names):
        path = ROOT / name
        if (name.startswith("/") or ".." in Path(name).parts or
                any(name.startswith(prefix) for prefix in DENIED) or
                any(part.startswith(".") for part in Path(name).parts) or
                path.is_symlink() or not path.is_file() or
                not stat.S_ISREG(path.stat().st_mode)):
            raise ValueError(f"不允许进入候选包的路径：{name}")
        data = path.read_bytes()
        if any(pattern.search(data) for pattern in SECRET):
            raise ValueError(f"文件可能含密钥，停止封包：{name}")
        members.append((name, data))
    if any(pattern.search(members[0][1]) for pattern in SECRET):
        raise ValueError("试用说明可能含密钥，停止封包")
    return members


def build(target: Path) -> dict[str, object]:
    target = target.expanduser().resolve()
    if target.exists():
        raise FileExistsError(f"候选包已存在，拒绝覆盖：{target}")
    members = _members()
    if not target.parent.is_dir() or target.parent.is_symlink():
        raise ValueError("候选包父目录不存在或不安全")
    with ZipFile(target, "x", compression=ZIP_DEFLATED, compresslevel=9) as bundle:
        for name, data in members:
            info = ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = ZIP_DEFLATED
            info.external_attr = (0o100644 << 16)
            bundle.writestr(info, data, compress_type=ZIP_DEFLATED, compresslevel=9)
    with ZipFile(target) as bundle:
        if bundle.testzip() is not None or bundle.namelist() != [name for name, _ in members]:
            raise ValueError("生成后的 ZIP 完整性或成员顺序检查失败")
    return {"file": str(target), "sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            "files": len(members), "bytes": target.stat().st_size}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", type=Path, help="全新本地候选 ZIP 路径，不覆盖旧文件")
    args = parser.parse_args()
    print(build(args.output))


if __name__ == "__main__":
    main()
