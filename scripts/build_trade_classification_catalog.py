"""Build the versioned Census commodity-name index from retained monthly ZIPs."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from tradeintel_ai.trade_classification_catalog import build_catalog


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    manifest = build_catalog(args.root)
    print(json.dumps({"catalog_version": manifest["catalog_version"],
                      "months": len(manifest["months"]),
                      "flows": sorted(manifest["dataset_versions"])}, ensure_ascii=False))


if __name__ == "__main__":
    main()
