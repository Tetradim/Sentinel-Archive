from __future__ import annotations

import csv
from io import StringIO
from typing import Any

from sentinel_archive.backtesting.models import BacktestReport


def report_to_json(report: BacktestReport) -> dict[str, Any]:
    return report.model_dump(mode="json")


def report_to_csv(report: BacktestReport) -> str:
    fields = [
        "symbol",
        "side",
        "quantity",
        "entry_time",
        "entry_price",
        "exit_time",
        "exit_price",
        "pnl",
        "fees",
        "mae",
        "mfe",
        "exit_reason",
    ]
    buffer = StringIO()
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for trade in report.trades:
        writer.writerow(trade.model_dump(mode="json"))
    return buffer.getvalue()
