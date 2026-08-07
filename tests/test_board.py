from pocyeah.board import board_path, build_board_html


def test_board_path_is_a_sibling_html():
    assert board_path("/d/recording-20260807.mov") == "/d/recording-20260807-board.html"


def test_build_board_html_embeds_every_pane_title_and_src():
    items = [("1  API", "rec-1-api.mov"), ("2  DB", "rec-2-db.mov")]
    html = build_board_html(items, title="my demo")
    assert "<!doctype html>" in html.lower()
    assert "my demo" in html
    for title, src in items:
        assert title in html
        assert src in html
    assert "<video" in html
    # the panel list is embedded as JSON for the client script
    assert '"src": "rec-1-api.mov"' in html or '"src":"rec-1-api.mov"' in html


def test_build_board_html_escapes_title():
    html = build_board_html([("A", "a.mov")], title="<script>x</script>")
    assert "<script>x</script>" not in html  # escaped in the page chrome
    assert "&lt;script&gt;" in html


def test_build_board_html_accepts_data_uri_src():
    html = build_board_html([("A", "data:video/mp4;base64,AAAA")])
    assert "data:video/mp4;base64,AAAA" in html
