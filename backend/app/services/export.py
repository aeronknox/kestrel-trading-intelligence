"""CSV downloads of backtest, paper-trading and research results.

Spreadsheet apps execute cells that start with = + - @ (and tab/CR) as formulas, so a
crafted text value could run when a CSV is opened ("CSV injection"). Text cells that
start with one of those characters are prefixed with a quote; numbers are written
as numbers so they stay usable.
"""

import csv
import io
import re
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from fastapi import Response

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _cell(value: object) -> object:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat()
    if isinstance(value, bool | int | float):
        return value
    text = str(value)
    return "'" + text if text.startswith(FORMULA_PREFIXES) else text


def iso(ts: int | float | None) -> str:
    """Unix seconds -> ISO 8601 UTC (empty for None)."""
    return "" if ts is None else datetime.fromtimestamp(ts, tz=UTC).isoformat()


def safe_filename(*parts: object) -> str:
    stem = "-".join(re.sub(r"[^A-Za-z0-9]+", "-", str(p)).strip("-").lower() for p in parts if p not in (None, ""))
    return (stem or "export")[:120] + ".csv"


def csv_response(filename: str, header: Sequence[str], rows: Iterable[Sequence[object]]) -> Response:
    buf = io.StringIO()
    writer = csv.writer(buf, lineterminator="\r\n")
    writer.writerow(header)
    for row in rows:
        writer.writerow([_cell(v) for v in row])
    # BOM so Excel detects UTF-8 (asset names, user-entered strategy names).
    return Response(
        content="﻿" + buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"', "Cache-Control": "no-store"},
    )
