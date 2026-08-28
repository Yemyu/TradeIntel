"""Stage 0 exercise: read a small CSV file without pandas.

The sample values are synthetic and exist only for learning.
Complete the two TODO sections after reading the stage 0 guide.
"""

import csv
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DATA_FILE = PROJECT_ROOT / "data" / "sample" / "trade_sample.csv"


def load_trade_rows(csv_path: Path) -> list[dict[str, str]]:
    """Return every data row in the CSV file as a dictionary."""
    # TODO 1: Open csv_path and convert csv.DictReader into a list.
    raise NotImplementedError("请完成 TODO 1：读取 CSV")


def calculate_total_trade_value(rows: list[dict[str, str]]) -> int:
    """Return the sum of trade_value_usd for all rows."""
    # TODO 2: Convert each trade_value_usd from text to int and add them.
    raise NotImplementedError("请完成 TODO 2：计算贸易总额")


if __name__ == "__main__":
    trade_rows = load_trade_rows(DATA_FILE)
    total_value = calculate_total_trade_value(trade_rows)

    print(f"数据行数: {len(trade_rows)}")
    print(f"第一行数据: {trade_rows[0]}")
    print(f"贸易总额: {total_value} 美元")

