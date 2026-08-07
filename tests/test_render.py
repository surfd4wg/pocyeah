import pytest

from pocyeah.layout import solve_grid
from pocyeah.render import MARGIN_CELLS, frame_geometry


def test_frame_size_is_even_and_accounts_for_margins():
    canvas = solve_grid("columns", 2, pane_cols=80, pane_rows=24)
    geom = frame_geometry(canvas, cell_w=9, cell_h=19)
    assert geom.width % 2 == 0
    assert geom.height % 2 == 0
    # at least canvas + both margins
    assert geom.width >= canvas.cols * 9 + 2 * MARGIN_CELLS * 9
    assert geom.height >= canvas.rows * 19 + 2 * MARGIN_CELLS * 19
    assert len(geom.panes) == 2


def test_odd_cell_product_is_rounded_up_not_down():
    # canvas 1x1 cell, odd cell metrics -> odd raw size, must round UP to even
    canvas = solve_grid("columns", 1, pane_cols=1, pane_rows=1)
    geom = frame_geometry(canvas, cell_w=9, cell_h=19)
    assert geom.width % 2 == 0 and geom.height % 2 == 0


def test_pane_rects_place_title_above_text():
    canvas = solve_grid("columns", 1, pane_cols=10, pane_rows=5)
    geom = frame_geometry(canvas, cell_w=9, cell_h=19)
    p = geom.panes[0]
    assert p.title.h == 19  # one cell tall
    assert p.text.y == p.title.y + 19  # text starts right below the title bar
    assert p.text.h == 5 * 19
    assert p.outer.h == (1 + 5) * 19
    assert p.title.w == p.text.w == 10 * 9


def test_second_column_is_offset_right():
    canvas = solve_grid("columns", 2, pane_cols=10, pane_rows=5)
    geom = frame_geometry(canvas, cell_w=9, cell_h=19)
    assert geom.panes[1].title.x > geom.panes[0].title.x


def test_rejects_nonpositive_cell_metrics():
    canvas = solve_grid("columns", 1, 10, 5)
    with pytest.raises(ValueError):
        frame_geometry(canvas, 0, 19)
