"""Frame drawing (effect edge, part of N7): snapshots + geometry -> RGB bytes.

The one place PIL and a font are used. Given the pure `FrameGeometry` (pixel
rectangles) and each pane's `Snapshot` (cell grid), it paints one video frame
and returns it as raw `rgb24` bytes — exactly what ffmpeg.build_encode_args
expects on stdin. Colour resolution lives in theme.py and geometry in render.py,
so this module is only glyphs and rectangles; its one testable invariant is that
every frame is `width * height * 3` bytes.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from PIL import Image, ImageDraw, ImageFont

from pocyeah.render import FrameGeometry
from pocyeah.terminal import Cell, Snapshot
from pocyeah.theme import Theme

# Bundled-font search order: a monospace face present on essentially every Linux
# image first, then common Windows/macOS fallbacks. The recorder lets an explicit
# path override this list.
_FONT_CANDIDATES = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf",
    "/usr/share/fonts/dejavu/DejaVuSansMono.ttf",
    "/Library/Fonts/DejaVuSansMono.ttf",
    "C:\\Windows\\Fonts\\consola.ttf",
    "C:\\Windows\\Fonts\\cour.ttf",
    "DejaVuSansMono.ttf",  # PIL searches its own bundled fonts / cwd
)


class FontError(Exception):
    """Raised when no usable monospace font can be loaded."""


@dataclass(frozen=True)
class LoadedFont:
    font: ImageFont.FreeTypeFont
    cell_w: int
    cell_h: int
    ascent: int


def load_font(size: int, path: str | None = None) -> LoadedFont:
    """Load a monospace font at `size` px and measure its fixed cell metrics.

    Tries `path` if given, else the built-in candidate list. The cell width is
    the glyph advance rounded up so no glyph is clipped; the cell height is the
    font's ascent+descent. Raises FontError if nothing loads.
    """
    candidates = (path, *(_FONT_CANDIDATES)) if path else _FONT_CANDIDATES
    last: Exception | None = None
    for cand in candidates:
        if not cand:
            continue
        try:
            font = ImageFont.truetype(cand, size)
        except OSError as e:  # noqa: PERF203 - tiny fixed list
            last = e
            continue
        ascent, descent = font.getmetrics()
        cell_w = max(1, math.ceil(font.getlength("M")))
        cell_h = max(1, ascent + descent)
        return LoadedFont(font=font, cell_w=cell_w, cell_h=cell_h, ascent=ascent)
    raise FontError(
        "no monospace font found; install DejaVu Sans Mono or pass a font path "
        f"(last error: {last})"
    )


def _runs(row: tuple[Cell, ...]):
    """Yield (start_col, text, fg, bg, bold, reverse) for maximal same-style runs."""
    if not row:
        return
    start = 0
    cur = row[0]
    text = [cur.char]
    for x in range(1, len(row)):
        c = row[x]
        same = (
            c.fg == cur.fg
            and c.bg == cur.bg
            and c.bold == cur.bold
            and c.reverse == cur.reverse
        )
        if same:
            text.append(c.char)
        else:
            yield start, "".join(text), cur.fg, cur.bg, cur.bold, cur.reverse
            start, cur, text = x, c, [c.char]
    yield start, "".join(text), cur.fg, cur.bg, cur.bold, cur.reverse


def _draw_pane(
    draw: ImageDraw.ImageDraw,
    snap: Snapshot,
    pixels,
    theme: Theme,
    lf: LoadedFont,
) -> None:
    cw, ch = lf.cell_w, lf.cell_h

    # Terminal background panel + title bar.
    o = pixels.outer
    draw.rectangle([o.x, o.y, o.x + o.w - 1, o.y + o.h - 1], fill=theme.bg)
    t = pixels.title
    draw.rectangle([t.x, t.y, t.x + t.w - 1, t.y + t.h - 1], fill=theme.title_bg)
    draw.text((t.x + cw // 2, t.y), snap.title, font=lf.font, fill=theme.title_fg)

    tx0, ty0 = pixels.text.x, pixels.text.y
    for y, row in enumerate(snap.rows):
        cy = ty0 + y * ch
        for start, text, fg, bg, bold, reverse in _runs(row):
            fg_rgb = theme.rgb(fg, bold=bold, foreground=True)
            bg_rgb = theme.rgb(bg, foreground=False)
            if reverse:
                fg_rgb, bg_rgb = bg_rgb, fg_rgb
            cx = tx0 + start * cw
            if bg_rgb != theme.bg:
                draw.rectangle(
                    [cx, cy, cx + len(text) * cw - 1, cy + ch - 1], fill=bg_rgb
                )
            if text.strip():
                draw.text((cx, cy), text, font=lf.font, fill=fg_rgb)

    if snap.cursor_visible and snap.cursor_y < len(snap.rows):
        cx = tx0 + snap.cursor_x * cw
        cy = ty0 + snap.cursor_y * ch
        draw.rectangle([cx, cy, cx + cw - 1, cy + ch - 1], fill=theme.cursor)
        # Redraw the covered glyph in the background colour so it stays legible.
        if snap.cursor_x < len(snap.rows[snap.cursor_y]):
            ch_cell = snap.rows[snap.cursor_y][snap.cursor_x]
            if ch_cell.char.strip():
                draw.text((cx, cy), ch_cell.char, font=lf.font, fill=theme.bg)


def render_frame(
    geom: FrameGeometry,
    snapshots: list[Snapshot],
    theme: Theme,
    lf: LoadedFont,
) -> bytes:
    """Paint one frame and return it as raw rgb24 bytes (width*height*3).

    `snapshots` are in pane order (matching `geom.panes`); a pane with no
    snapshot yet (not launched) draws as an empty terminal panel so the layout
    holds steady from the first frame.
    """
    img = Image.new("RGB", (geom.width, geom.height), theme.bg)
    draw = ImageDraw.Draw(img)
    for i, pixels in enumerate(geom.panes):
        snap = snapshots[i] if i < len(snapshots) and snapshots[i] is not None else None
        if snap is None:
            o = pixels.outer
            draw.rectangle([o.x, o.y, o.x + o.w - 1, o.y + o.h - 1], fill=theme.bg)
            t = pixels.title
            draw.rectangle([t.x, t.y, t.x + t.w - 1, t.y + t.h - 1], fill=theme.title_bg)
            continue
        _draw_pane(draw, snap, pixels, theme, lf)
    return img.tobytes()
