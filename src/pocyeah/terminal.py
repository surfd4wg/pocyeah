"""In-process terminal emulation (effect edge, part of N7).

Wraps `pyte` — a pure-Python VT/ANSI emulator — so each pane's raw PTY byte
stream becomes a fixed `cols x rows` grid of coloured cells that frame.py can
draw. pyte itself does no I/O; the only reason this is an effect edge rather
than pure is that it holds mutable emulator state fed incrementally as bytes
arrive. The snapshot it produces IS plain data, so the drawing path can be
reasoned about (and its geometry tested) without a live emulator.
"""
from __future__ import annotations

from dataclasses import dataclass

import pyte


@dataclass(frozen=True)
class Cell:
    """One rendered character cell: its glyph, colours, and emphasis."""

    char: str
    fg: str  # a pyte colour token: an ANSI name, 'default', or 6 hex digits
    bg: str
    bold: bool
    reverse: bool


@dataclass(frozen=True)
class Snapshot:
    """A whole pane at one instant: its title, its cell grid, and the cursor."""

    title: str
    rows: tuple[tuple[Cell, ...], ...]
    cursor_x: int
    cursor_y: int
    cursor_visible: bool


class Terminal:
    """A single pane's emulator: fixed size, fed bytes, snapshotted per frame."""

    def __init__(self, title: str, cols: int, rows: int) -> None:
        self.title = title
        self.cols = cols
        self.rows = rows
        self._screen = pyte.Screen(cols, rows)
        # bytes -> screen. errors="ignore" keeps a stray non-UTF-8 byte from a
        # noisy program from ever aborting a take mid-render.
        self._stream = pyte.ByteStream(self._screen)

    def feed(self, data: bytes) -> None:
        """Advance the emulator by `data`. Empty input is a cheap no-op."""
        if data:
            self._stream.feed(data)

    def snapshot(self) -> Snapshot:
        """Freeze the current screen into plain, immutable cell data."""
        buffer = self._screen.buffer
        rows: list[tuple[Cell, ...]] = []
        for y in range(self.rows):
            line = buffer[y]
            cells: list[Cell] = []
            for x in range(self.cols):
                ch = line[x]
                cells.append(
                    Cell(
                        char=ch.data or " ",
                        fg=ch.fg,
                        bg=ch.bg,
                        bold=bool(ch.bold),
                        reverse=bool(ch.reverse),
                    )
                )
            rows.append(tuple(cells))
        cursor = self._screen.cursor
        return Snapshot(
            title=self.title,
            rows=tuple(rows),
            cursor_x=cursor.x,
            cursor_y=cursor.y,
            cursor_visible=not self._screen.cursor.hidden,
        )
