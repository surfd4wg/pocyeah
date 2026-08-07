"""Pure frame geometry (part of N7): a cell canvas -> pixel rectangles.

Given the tiling solver's `Canvas` (in character cells) and the font's cell
metrics (width/height in pixels), this computes the exact pixel size of the
video frame and where every pane's title bar and text area land in it. It is
deliberately pure — no PIL, no font object — so the geometry is unit-testable
and frame.py is left with only the drawing. libx264 under yuv420p rejects odd
dimensions, so the frame size is rounded up to even here, once.
"""
from __future__ import annotations

from dataclasses import dataclass

from pocyeah.layout import Canvas, PaneBox

MARGIN_CELLS = 1  # outer padding around the whole canvas, in cell widths/heights


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int


@dataclass(frozen=True)
class PanePixels:
    """One pane's pixel rectangles: the title bar, the text area, and the union."""

    title: Rect
    text: Rect
    outer: Rect


@dataclass(frozen=True)
class FrameGeometry:
    width: int
    height: int
    cell_w: int
    cell_h: int
    margin_x: int
    margin_y: int
    panes: tuple[PanePixels, ...]


def _even(n: int) -> int:
    """Round up to the nearest even number (yuv420p needs even W/H)."""
    return n + (n & 1)


def _pane_pixels(box: PaneBox, cell_w: int, cell_h: int, mx: int, my: int) -> PanePixels:
    x = mx + box.col * cell_w
    title_y = my + box.title_row * cell_h
    text_y = my + box.text_row * cell_h
    w = box.cols * cell_w
    return PanePixels(
        title=Rect(x=x, y=title_y, w=w, h=cell_h),
        text=Rect(x=x, y=text_y, w=w, h=box.rows * cell_h),
        outer=Rect(x=x, y=title_y, w=w, h=box.total_rows * cell_h),
    )


def frame_geometry(canvas: Canvas, cell_w: int, cell_h: int) -> FrameGeometry:
    """Resolve a cell `canvas` to a pixel frame + per-pane rectangles.

    The frame is `canvas` cells plus a one-cell margin all around, its width and
    height each rounded up to even. Any pixel added by that rounding is margin,
    so pane rectangles never shift.
    """
    if cell_w < 1 or cell_h < 1:
        raise ValueError("cell metrics must be positive")
    mx = MARGIN_CELLS * cell_w
    my = MARGIN_CELLS * cell_h
    width = _even(canvas.cols * cell_w + 2 * mx)
    height = _even(canvas.rows * cell_h + 2 * my)
    panes = tuple(_pane_pixels(b, cell_w, cell_h, mx, my) for b in canvas.boxes)
    return FrameGeometry(
        width=width,
        height=height,
        cell_w=cell_w,
        cell_h=cell_h,
        margin_x=mx,
        margin_y=my,
        panes=panes,
    )
