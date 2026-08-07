from pocyeah.terminal import Cell, Snapshot, Terminal


def test_feed_plain_text_appears_in_snapshot():
    term = Terminal("T", cols=20, rows=3)
    term.feed(b"hello")
    snap = term.snapshot()
    assert isinstance(snap, Snapshot)
    assert snap.title == "T"
    assert len(snap.rows) == 3
    assert len(snap.rows[0]) == 20
    text = "".join(c.char for c in snap.rows[0]).rstrip()
    assert text == "hello"
    assert all(isinstance(c, Cell) for c in snap.rows[0])


def test_ansi_colour_is_captured_per_cell():
    term = Terminal("T", cols=20, rows=1)
    term.feed(b"\x1b[31mRED\x1b[0m X")
    row = term.snapshot().rows[0]
    assert row[0].char == "R"
    assert row[0].fg == "red"
    # after the reset, colour returns to default
    assert row[4].fg == "default"


def test_empty_feed_is_a_noop():
    term = Terminal("T", cols=5, rows=1)
    term.feed(b"")
    assert "".join(c.char for c in term.snapshot().rows[0]).strip() == ""


def test_invalid_utf8_does_not_crash():
    term = Terminal("T", cols=10, rows=1)
    term.feed(b"ok\xff\xfebye")  # stray non-UTF-8 bytes
    snap = term.snapshot()  # must not raise
    assert "ok" in "".join(c.char for c in snap.rows[0])


def test_cursor_position_reported():
    term = Terminal("T", cols=10, rows=2)
    term.feed(b"abc")
    snap = term.snapshot()
    assert snap.cursor_x == 3
    assert snap.cursor_y == 0
    assert snap.cursor_visible is True
