"""Pure tiling solver (N4): pane count + mode -> a character-cell canvas.

The old solver placed real Terminal.app windows in screen *points*; the portable
recorder renders its own terminals, so tiling is now in character *cells*. Each
pane is a `cols x rows` grid with a one-line title bar above it; this module
decides where every pane sits on one composite canvas, and how big that canvas
is. render.py turns these cell coordinates into pixels; nothing here touches a
screen, a font, or ffmpeg, so it stays exhaustively unit-testable.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

TITLE_ROWS = 1  # a single title-bar line sits atop each pane's text area
GAP_X = 2  # blank cell columns between side-by-side panes
GAP_Y = 1  # blank cell rows between stacked panes


@dataclass(frozen=True)
class PaneBox:
    """One pane's place on the canvas, in character cells.

    `col`/`row` are the top-left of the pane's *title bar*; the `rows` text lines
    begin one row below it. `cols` is the shared width of the title bar and the
    text area.
    """

    col: int
    row: int
    cols: int
    rows: int

    @property
    def title_row(self) -> int:
        return self.row

    @property
    def text_row(self) -> int:
        return self.row + TITLE_ROWS

    @property
    def total_rows(self) -> int:
        return TITLE_ROWS + self.rows


@dataclass(frozen=True)
class Canvas:
    """The whole composite: its size in cells plus each pane's box."""

    cols: int
    rows: int
    boxes: tuple[PaneBox, ...]


def _grid_shape(mode: str, n: int) -> tuple[int, int]:
    """(columns, rows) of the tile arrangement for `n` panes in `mode`."""
    if mode == "columns":
        return n, 1
    if mode == "rows":
        return 1, n
    if mode == "grid":
        cols = math.ceil(math.sqrt(n))
        rows = math.ceil(n / cols)
        return cols, rows
    raise ValueError(f"unknown layout mode: {mode!r}")


def solve_grid(mode: str, n: int, pane_cols: int, pane_rows: int) -> Canvas:
    """Tile `n` uniform `pane_cols x pane_rows` panes on one cell canvas.

    Panes fill the arrangement row-major (left to right, top to bottom), the same
    order they launch. The canvas is sized to the widest tile row and the full
    stack height, including the inter-pane gaps and each pane's title bar. An
    incomplete final grid row is left-aligned; the canvas still spans the full
    width of a complete row so every frame in a take is the same size.
    """
    if n < 1:
        raise ValueError("layout needs at least one pane")
    if pane_cols < 1 or pane_rows < 1:
        raise ValueError("pane dimensions must be positive")

    cols, rows = _grid_shape(mode, n)
    box_h = TITLE_ROWS + pane_rows

    boxes: list[PaneBox] = []
    for i in range(n):
        c = i % cols
        r = i // cols
        col = c * (pane_cols + GAP_X)
        row = r * (box_h + GAP_Y)
        boxes.append(PaneBox(col=col, row=row, cols=pane_cols, rows=pane_rows))

    canvas_cols = cols * pane_cols + (cols - 1) * GAP_X
    canvas_rows = rows * box_h + (rows - 1) * GAP_Y
    return Canvas(cols=canvas_cols, rows=canvas_rows, boxes=tuple(boxes))
