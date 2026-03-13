from __future__ import annotations

import re
from dataclasses import dataclass


_GRID_POINT_RE = re.compile(r"^\s*([A-Za-z]+)(\d+)\s*$")


@dataclass(frozen=True, slots=True)
class GridPoint:
    row: int
    col: int


@dataclass(frozen=True, slots=True)
class GridRegion:
    row_start: int
    col_start: int
    row_end: int
    col_end: int

    @property
    def width(self) -> int:
        return self.col_end - self.col_start + 1

    @property
    def height(self) -> int:
        return self.row_end - self.row_start + 1


def row_label_to_index(label: str) -> int:
    """Convert Excel-style row labels to zero-based indices."""
    label = label.strip().upper()
    if not label.isalpha():
        raise ValueError(f"Invalid row label: {label!r}")
    value = 0
    for char in label:
        value = (value * 26) + (ord(char) - ord("A") + 1)
    return value - 1


def index_to_row_label(index: int) -> str:
    """Convert a zero-based row index to an Excel-style row label."""
    if index < 0:
        raise ValueError("Row index must be >= 0")
    index += 1
    chars: list[str] = []
    while index:
        index, remainder = divmod(index - 1, 26)
        chars.append(chr(ord("A") + remainder))
    return "".join(reversed(chars))


def parse_grid_point(token: str) -> GridPoint:
    """Parse a grid point like A0 or AB12."""
    match = _GRID_POINT_RE.match(token)
    if not match:
        raise ValueError(f"Invalid grid token: {token!r}")
    row_label, col_str = match.groups()
    return GridPoint(row=row_label_to_index(row_label), col=int(col_str))


def parse_grid_region(label: str) -> GridRegion:
    """Parse A0, A0-A1, or A0-B3 into a normalized region."""
    raw = label.strip()
    if "-" in raw:
        left, right = [part.strip() for part in raw.split("-", 1)]
        a = parse_grid_point(left)
        b = parse_grid_point(right)
        row_start, row_end = sorted([a.row, b.row])
        col_start, col_end = sorted([a.col, b.col])
        return GridRegion(
            row_start=row_start,
            col_start=col_start,
            row_end=row_end,
            col_end=col_end,
        )
    point = parse_grid_point(raw)
    return GridRegion(
        row_start=point.row,
        col_start=point.col,
        row_end=point.row,
        col_end=point.col,
    )


def grid_region_to_label(region: GridRegion) -> str:
    start = f"{index_to_row_label(region.row_start)}{region.col_start}"
    end = f"{index_to_row_label(region.row_end)}{region.col_end}"
    return start if start == end else f"{start}-{end}"


def regions_overlap(a: GridRegion, b: GridRegion) -> bool:
    row_disjoint = a.row_end < b.row_start or b.row_end < a.row_start
    col_disjoint = a.col_end < b.col_start or b.col_end < a.col_start
    return not row_disjoint and not col_disjoint


def region_within_bounds(region: GridRegion, rows: int, cols: int) -> bool:
    return (
        0 <= region.row_start <= region.row_end < rows
        and 0 <= region.col_start <= region.col_end < cols
    )
