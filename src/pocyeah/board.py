"""Pure HTML "board" generation for `--split` takes (N16-adjacent). No I/O.

`record --split` writes one video per pane; this builds a single self-contained
HTML page that tiles those videos as **draggable, resizable** panels, so the
viewer gets the multi-terminal layout in one window and can arrange the panes on
their monitor without juggling separate player apps. The page is pure inline
HTML/CSS/JS — no build step, no network, no dependencies — so it opens straight
from disk. Kept pure (returns a string) so it is unit-testable; the CLI writes it.

`src` for each pane is whatever the caller passes: a relative filename (the
default — the videos sit beside the HTML) or a `data:` URI (a fully embedded,
portable single file). This module does not care which.
"""
from __future__ import annotations

import html
import json
import os

_TEMPLATE = """\
<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>__TITLE__</title>
<style>
  :root { --bg:#12141a; --panel:#1b1e26; --bar:#2a2e3a; --ink:#e6e8ee; --dim:#8b90a0; --accent:#61afef; }
  * { box-sizing: border-box; }
  html, body { margin:0; height:100%; background:var(--bg); color:var(--ink);
    font-family: ui-sans-serif, system-ui, -apple-system, Segoe UI, Roboto, sans-serif; }
  #toolbar { position:fixed; z-index:10000; top:0; left:0; right:0; height:44px;
    display:flex; align-items:center; gap:8px; padding:0 12px; background:rgba(20,22,28,.9);
    backdrop-filter: blur(6px); border-bottom:1px solid #000; }
  #toolbar .title { font-weight:600; margin-right:auto; letter-spacing:.2px; }
  #toolbar .title small { color:var(--dim); font-weight:400; margin-left:8px; }
  button { background:var(--bar); color:var(--ink); border:1px solid #000; border-radius:7px;
    padding:6px 12px; font-size:13px; cursor:pointer; }
  button:hover { background:#333846; }
  #board { position:absolute; inset:44px 0 0 0; overflow:hidden; }
  .panel { position:absolute; background:var(--panel); border:1px solid #000;
    border-radius:10px; box-shadow:0 10px 30px rgba(0,0,0,.5); overflow:hidden;
    min-width:220px; min-height:150px; display:flex; flex-direction:column; }
  .panel .head { height:30px; flex:0 0 30px; display:flex; align-items:center; gap:8px;
    padding:0 10px; background:var(--bar); cursor:move; user-select:none; font-size:13px; }
  .panel .head .dot { width:9px; height:9px; border-radius:50%; background:var(--accent); flex:0 0 auto; }
  .panel .head .name { font-weight:600; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
  .panel video { flex:1 1 auto; width:100%; height:100%; object-fit:contain; background:#000; display:block; }
  .panel .grip { position:absolute; right:2px; bottom:2px; width:16px; height:16px; cursor:nwse-resize;
    background:linear-gradient(135deg, transparent 45%, var(--dim) 45%, var(--dim) 55%, transparent 55%);
    opacity:.7; }
  .hint { position:fixed; bottom:10px; left:50%; transform:translateX(-50%); color:var(--dim);
    font-size:12px; z-index:9999; pointer-events:none; }
</style>
</head>
<body>
<div id="toolbar">
  <div class="title">__TITLE__ <small>drag by the bar · resize from the corner</small></div>
  <button id="replay">↻ Replay all</button>
  <button id="playpause">⏸ Pause</button>
  <button id="retile">⤢ Retile</button>
</div>
<div id="board"></div>
<div class="hint">Panes are independent videos on the same clock — arrange them anywhere.</div>
<script>
const PANES = __PANELS__;
const board = document.getElementById('board');
let z = 1;

function tile() {
  const pad = 16, bw = board.clientWidth, bh = board.clientHeight;
  const n = PANES.length;
  const cols = Math.ceil(Math.sqrt(n));
  const rows = Math.ceil(n / cols);
  const w = Math.max(240, Math.floor((bw - pad * (cols + 1)) / cols));
  const h = Math.max(170, Math.floor((bh - pad * (rows + 1)) / rows));
  [...board.children].forEach((el, i) => {
    const c = i % cols, r = Math.floor(i / cols);
    el.style.left = (pad + c * (w + pad)) + 'px';
    el.style.top  = (pad + r * (h + pad)) + 'px';
    el.style.width = w + 'px';
    el.style.height = h + 'px';
  });
}

function makePanel(pane) {
  const el = document.createElement('div');
  el.className = 'panel';
  el.innerHTML =
    '<div class="head"><span class="dot"></span><span class="name"></span></div>' +
    '<video autoplay loop muted playsinline></video>' +
    '<div class="grip"></div>';
  el.querySelector('.name').textContent = pane.title;
  el.querySelector('video').src = pane.src;
  board.appendChild(el);

  const bring = () => { el.style.zIndex = ++z; };
  el.addEventListener('pointerdown', bring);

  // Drag by the header
  const head = el.querySelector('.head');
  head.addEventListener('pointerdown', e => {
    bring();
    const sx = e.clientX, sy = e.clientY;
    const ox = el.offsetLeft, oy = el.offsetTop;
    head.setPointerCapture(e.pointerId);
    const move = ev => { el.style.left = (ox + ev.clientX - sx) + 'px';
                         el.style.top  = (oy + ev.clientY - sy) + 'px'; };
    const up = () => { head.removeEventListener('pointermove', move);
                       head.removeEventListener('pointerup', up); };
    head.addEventListener('pointermove', move);
    head.addEventListener('pointerup', up);
  });

  // Resize from the corner grip
  const grip = el.querySelector('.grip');
  grip.addEventListener('pointerdown', e => {
    e.stopPropagation(); bring();
    const sx = e.clientX, sy = e.clientY;
    const ow = el.offsetWidth, oh = el.offsetHeight;
    grip.setPointerCapture(e.pointerId);
    const move = ev => { el.style.width  = Math.max(220, ow + ev.clientX - sx) + 'px';
                         el.style.height = Math.max(150, oh + ev.clientY - sy) + 'px'; };
    const up = () => { grip.removeEventListener('pointermove', move);
                       grip.removeEventListener('pointerup', up); };
    grip.addEventListener('pointermove', move);
    grip.addEventListener('pointerup', up);
  });
  return el;
}

PANES.forEach(makePanel);
tile();

const vids = () => [...board.querySelectorAll('video')];
document.getElementById('replay').onclick = () =>
  vids().forEach(v => { v.currentTime = 0; v.play(); });
let playing = true;
document.getElementById('playpause').onclick = e => {
  playing = !playing;
  vids().forEach(v => playing ? v.play() : v.pause());
  e.target.textContent = playing ? '⏸ Pause' : '▶ Play';
};
document.getElementById('retile').onclick = tile;
window.addEventListener('resize', tile);
</script>
</body>
</html>
"""


def board_path(out_path: str) -> str:
    """`.../recording-<stamp>.mov` -> `.../recording-<stamp>-board.html` (a sibling)."""
    root, _ = os.path.splitext(out_path)
    return f"{root}-board.html"


def build_board_html(items: list[tuple[str, str]], title: str = "pocyeah board") -> str:
    """Render the draggable/resizable video board for `items` = [(title, src), …].

    `src` is embedded verbatim as each `<video>`'s source — a relative filename
    (videos beside the HTML) or a `data:` URI (a self-contained single file).
    Pure: returns the HTML string; the caller writes it to disk.
    """
    panels = json.dumps([{"title": t, "src": s} for t, s in items])
    return _TEMPLATE.replace("__TITLE__", html.escape(title)).replace("__PANELS__", panels)
