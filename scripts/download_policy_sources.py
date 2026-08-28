"""Download and verify the official USTR List 1 source notices."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import Request, urlopen


PROJECT_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_DIR = PROJECT_ROOT / "data/raw/policy"
MANIFEST_PATH = OUTPUT_DIR / "source_manifest.json"
SOURCES = (
    {
        "name": "initial_notice",
        "url": "https://ustr.gov/sites/default/files/2018-13248.pdf",
        "filename": "ustr-section301-list1-2018.pdf",
        "sha256": "3e27dfb420dc308a079e7a71f2715fa29ed00fbbd84dbec4514f2cd66b9cf301",
    },
    {
        "name": "amendment_notice",
        "url": (
            "https://ustr.gov/sites/default/files/enforcement/"
            "301Investigations/2018-17709.pdf"
        ),
        "filename": "ustr-section301-list1-amendment-2018-08-16.pdf",
        "sha256": "97a1883d0617b038e4b5bd2f6e36400168fcc27d67fe6562149cc85866c08729",
    },
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def download_source(source: dict[str, str]) -> dict[str, object]:
    destination = OUTPUT_DIR / source["filename"]
    if destination.exists() and sha256_file(destination) == source["sha256"]:
        status = "already_verified"
    else:
        temporary = destination.with_suffix(".pdf.part")
        request = Request(source["url"], headers={"User-Agent": "TradeShockAI/0.1"})
        with urlopen(request, timeout=60) as response, temporary.open("wb") as file:
            while chunk := response.read(1024 * 1024):
                file.write(chunk)

        actual_hash = sha256_file(temporary)
        if actual_hash != source["sha256"]:
            temporary.unlink(missing_ok=True)
            raise ValueError(
                f"Checksum mismatch for {source['name']}: {actual_hash}"
            )
        temporary.replace(destination)
        status = "downloaded_and_verified"

    return {
        **source,
        "local_path": str(destination.relative_to(PROJECT_ROOT)),
        "bytes": destination.stat().st_size,
        "status": status,
    }


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    records = [download_source(source) for source in SOURCES]
    manifest = {
        "retrieved_at_utc": datetime.now(timezone.utc).isoformat(),
        "sources": records,
    }
    with MANIFEST_PATH.open("w", encoding="utf-8") as file:
        json.dump(manifest, file, indent=2)
        file.write("\n")

    for record in records:
        print(f"{record['name']}: {record['status']}")
    print(f"Wrote {MANIFEST_PATH.relative_to(PROJECT_ROOT)}")


if __name__ == "__main__":
    main()

