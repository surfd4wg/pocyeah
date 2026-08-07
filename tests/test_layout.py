import pytest

from pocyeah.layout import GAP_X, GAP_Y, TITLE_ROWS, Canvas, solve_grid


def test_columns_places_panes_side_by_side():
    canvas = solve_grid("columns", 3, pane_cols=80, pane_rows=24)
    assert isinstance(canvas, Canvas)
    assert len(canvas.boxes) == 3
    # all on the same top row, each a title bar + text area tall
    assert {b.row for b in canvas.boxes} == {0}
    assert all(b.cols == 80 and b.rows == 24 for b in canvas.boxes)
    cols = [b.col for b in canvas.boxes]
    assert cols == [0, 80 + GAP_X, 2 * (80 + GAP_X)]
    assert canvas.cols == 3 * 80 + 2 * GAP_X
    assert canvas.rows == TITLE_ROWS + 24


def test_rows_stacks_panes():
    canvas = solve_grid("rows", 2, pane_cols=60, pane_rows=10)
    assert {b.col for b in canvas.boxes} == {0}
    box_h = TITLE_ROWS + 10
    assert [b.row for b in canvas.boxes] == [0, box_h + GAP_Y]
    assert canvas.cols == 60
    assert canvas.rows == 2 * box_h + GAP_Y


def test_grid_uses_ceil_sqrt_shape():
    canvas = solve_grid("grid", 4, pane_cols=40, pane_rows=12)
    # 4 panes -> 2x2
    positions = {(b.col, b.row) for b in canvas.boxes}
    box_h = TITLE_ROWS + 12
    assert positions == {
        (0, 0),
        (40 + GAP_X, 0),
        (0, box_h + GAP_Y),
        (40 + GAP_X, box_h + GAP_Y),
    }


def test_grid_incomplete_last_row_is_left_aligned_but_canvas_spans_full_width():
    canvas = solve_grid("grid", 3, pane_cols=40, pane_rows=12)  # 2 cols x 2 rows
    # the lone third pane sits at column 0 of the second row
    third = canvas.boxes[2]
    assert third.col == 0
    # canvas still spans a full two-column row so every frame is the same size
    assert canvas.cols == 2 * 40 + GAP_X


def test_pane_box_derived_rows():
    canvas = solve_grid("columns", 1, pane_cols=80, pane_rows=24)
    b = canvas.boxes[0]
    assert b.title_row == b.row
    assert b.text_row == b.row + TITLE_ROWS
    assert b.total_rows == TITLE_ROWS + 24


def test_unknown_mode_and_bad_counts_raise():
    with pytest.raises(ValueError, match="unknown layout mode"):
        solve_grid("sideways", 1, 80, 24)
    with pytest.raises(ValueError):
        solve_grid("columns", 0, 80, 24)
    with pytest.raises(ValueError):
        solve_grid("columns", 1, 0, 24)
