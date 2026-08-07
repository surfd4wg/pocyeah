import pytest

from pocyeah.frame import FontError, load_font, render_frame
from pocyeah.layout import solve_grid
from pocyeah.render import frame_geometry
from pocyeah.terminal import Terminal
from pocyeah.theme import DARK


def _geom_and_font():
    lf = load_font(16)
    canvas = solve_grid("columns", 2, pane_cols=40, pane_rows=8)
    geom = frame_geometry(canvas, lf.cell_w, lf.cell_h)
    return geom, lf


def test_load_font_reports_positive_cell_metrics():
    lf = load_font(16)
    assert lf.cell_w > 0 and lf.cell_h > 0
    assert lf.ascent > 0


def test_load_font_raises_when_nothing_loads(monkeypatch):
    # Force every candidate (and the explicit path) to be unloadable.
    from pocyeah import frame

    monkeypatch.setattr(frame, "_FONT_CANDIDATES", ("/no/such/font.ttf",))
    with pytest.raises(FontError):
        load_font(16, path="/also/missing.ttf")


def test_render_frame_returns_exact_rgb_byte_count():
    geom, lf = _geom_and_font()
    t1 = Terminal("A", 40, 8)
    t1.feed(b"hello world")
    snaps = [t1.snapshot(), None]  # one live pane, one not-yet-launched
    frame = render_frame(geom, snaps, DARK, lf)
    assert isinstance(frame, (bytes, bytearray))
    assert len(frame) == geom.width * geom.height * 3


def test_render_frame_tolerates_missing_snapshots_list():
    geom, lf = _geom_and_font()
    frame = render_frame(geom, [], DARK, lf)  # nothing launched yet
    assert len(frame) == geom.width * geom.height * 3


def test_render_frame_content_changes_with_input():
    geom, lf = _geom_and_font()
    blank = render_frame(geom, [Terminal("A", 40, 8).snapshot(), None], DARK, lf)
    t = Terminal("A", 40, 8)
    t.feed(b"\x1b[31mLOTS OF RED TEXT HERE\x1b[0m")
    filled = render_frame(geom, [t.snapshot(), None], DARK, lf)
    assert blank != filled  # drawing text actually changed pixels
