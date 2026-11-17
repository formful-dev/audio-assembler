"""Reading the order list (CSV).

Columns, in this order: order number, track label, segment number, gap after the segment in seconds.
A header row is optional. Separator: comma, semicolon or tab. Decimal point or decimal comma.
"""

from __future__ import annotations

import csv
import io
import math
from dataclasses import dataclass
from pathlib import Path

from .errors import OrderListError

COLUMNS_HELP = "order number, track label, segment number, gap in seconds"
MAX_REPORTED = 20


@dataclass(frozen=True)
class OrderRow:
    row: int        # row number in the list, counting from 1, header not counted
    order: float
    order_text: str
    label: str
    segment: int
    gap: float


@dataclass
class OrderList:
    path: str
    rows: list[OrderRow]   # sorted by order number
    separator: str
    has_header: bool

    def labels(self) -> set[str]:
        return {r.label.casefold() for r in self.rows}

    def max_segment(self, label: str) -> int:
        key = label.casefold()
        return max((r.segment for r in self.rows if r.label.casefold() == key), default=0)

    def used_segments(self, label: str) -> set[int]:
        key = label.casefold()
        return {r.segment for r in self.rows if r.label.casefold() == key}

    @property
    def total_gap(self) -> float:
        return sum(r.gap for r in self.rows)


def parse_number(text: str) -> float:
    t = text.strip().replace(" ", "").replace(" ", "")
    if "," in t and "." not in t:
        t = t.replace(",", ".")
    value = float(t)
    if not math.isfinite(value):
        raise ValueError(text)
    return value


def _decode(raw: bytes) -> str:
    try:
        return raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        return raw.decode("cp1252", errors="replace")


def _pick_separator(first_line: str) -> str:
    counts = {sep: first_line.count(sep) for sep in (";", "\t", ",")}
    for sep in (";", "\t", ","):  # semicolon first: commas may be decimal commas
        if counts[sep] >= 3:
            return sep
    best = max(counts, key=counts.get)
    return best if counts[best] else ","


def read_order_list(path: str) -> OrderList:
    name = Path(path).name
    try:
        raw = Path(path).read_bytes()
    except FileNotFoundError:
        raise OrderListError(f"The order list '{name}' was not found.",
                             "Check that the file still exists and choose it again.") from None
    except OSError as e:
        raise OrderListError(f"Could not open the order list '{name}'.",
                             "Close it in Excel or any other program and try again.", [str(e)]) from None
    return parse_order_list(_decode(raw), path)


def parse_order_list(text: str, path: str = "order list") -> OrderList:
    name = Path(path).name
    lines = text.splitlines()
    first = next((ln for ln in lines if ln.strip().strip(",;\t")), "")
    if not first:
        raise OrderListError(f"The order list '{name}' is empty.",
                             f"Add one row per segment with the columns: {COLUMNS_HELP}.")
    sep = _pick_separator(first)
    records = [r for r in csv.reader(io.StringIO(text), delimiter=sep)
               if any(cell.strip() for cell in r)]

    header = records[0]
    has_header = True
    try:
        parse_number(header[0])
        has_header = False
    except (ValueError, IndexError):
        pass
    width = len(header) if has_header else 4
    data = records[1:] if has_header else records

    if has_header and len(header) < 4:
        raise OrderListError(
            f"The order list '{name}' has only {len(header)} column(s), but it needs 4.",
            f"Use 4 columns in this order: {COLUMNS_HELP}. Example header: order,language,segment,gap_seconds",
        )
    if not data:
        raise OrderListError(f"The order list '{name}' has no rows below the header.",
                             "Add one row for each segment you want in the finished file.")

    problems: list[str] = []
    rows: list[OrderRow] = []
    for i, rec in enumerate(data, start=1):
        cells = [c.strip() for c in rec]
        if len(cells) < 4 or any(not c for c in cells[:4]):
            problems.append(f"Row {i}: a value is missing. Each row needs: {COLUMNS_HELP}.")
            continue
        if len(cells) > width and any(cells[width:]):
            if sep == ",":
                problems.append(f"Row {i} has more values than columns. If the gap uses a decimal comma "
                                "(like 2,5), save the list with semicolons, or use a decimal point (2.5).")
            else:
                problems.append(f"Row {i} has more values than the header has columns.")
            continue
        order_t, label, seg_t, gap_t = cells[:4]
        try:
            order = parse_number(order_t)
        except ValueError:
            problems.append(f"Row {i}: the order number '{order_t}' is not a number.")
            continue
        try:
            seg_f = parse_number(seg_t)
            if seg_f != int(seg_f) or seg_f < 1:
                raise ValueError
            seg = int(seg_f)
        except ValueError:
            problems.append(f"Row {i}: the segment number '{seg_t}' must be a whole number of 1 or more.")
            continue
        try:
            gap = parse_number(gap_t)
            if gap < 0:
                raise ValueError
        except ValueError:
            problems.append(f"Row {i}: the gap '{gap_t}' must be a number of seconds, 0 or more "
                            "(for example 2 or 1.5).")
            continue
        rows.append(OrderRow(i, order, order_t, label, seg, gap))

    seen: dict[float, int] = {}
    for r in rows:
        if r.order in seen:
            problems.append(f"Row {r.row}: the order number {r.order_text} is also used in row {seen[r.order]}. "
                            "Each order number must be used once.")
        else:
            seen[r.order] = r.row

    if problems:
        shown = problems[:MAX_REPORTED]
        if len(problems) > MAX_REPORTED:
            shown.append(f"... and {len(problems) - MAX_REPORTED} more problems.")
        raise OrderListError(f"The order list '{name}' has problems:",
                             "Correct these rows in the order list, save it, and try again.", shown)

    rows.sort(key=lambda r: r.order)
    return OrderList(path, rows, sep, has_header)
