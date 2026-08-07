"""Portable recorder edge (N9) and take pruning (N12/R8.1).

The take is produced entirely in-process: each pane's command runs in a PTY
(ptyio), its bytes drive an in-memory terminal emulator (terminal.py), every
frame is painted with PIL (frame.py) and piped as raw RGB into ffmpeg
(ffmpeg.build_encode_args). No Terminal.app, no AppleScript, no screen-recording
permission and no display server — so a take runs the same on Linux, Windows and
macOS, and headless CI can record one.

The event timeline is captured exactly as before — first-appearance offsets of
each pane-open marker and each handshake signal — so the `.timeline.json`
sidecar contract that `annotate`/`narrate` depend on is unchanged. The pure
subtitle/narration/overlay pipeline downstream did not move.

`split=True` renders each pane to its OWN independent video (one encoder per
pane) instead of a single composite — detachable windows the viewer can arrange
freely on a monitor. Every output still gets its own timeline sidecar.
"""
from __future__ import annotations

import glob
import os
import re
import subprocess
import time

from pocyeah.cmd import pane_env
from pocyeah.ffmpeg import build_encode_args
from pocyeah.frame import load_font, render_frame
from pocyeah.gates import resolve_steps, signal_path
from pocyeah.layout import solve_grid
from pocyeah.naming import out_glob, select_prunable
from pocyeah.ptyio import open_pane
from pocyeah.render import frame_geometry
from pocyeah.spec import Spec
from pocyeah.subtitles import build_timeline_json, marker_path, timeline_watches
from pocyeah.terminal import Terminal
from pocyeah.theme import get_theme
from pocyeah.verify import check_expectations

SETTLE_S = 1.0  # blank lead-in so ffmpeg is writing frames before the first pane
POLL_S = 0.02  # sequencing granularity when the frame loop would otherwise idle


class RecordError(Exception):
    """Raised when the recorder cannot be started or ffmpeg fails a take."""


def _write_timeline(path: str, offsets: dict[str, float]) -> None:
    """Write the timeline sidecar. Best-effort: the take has already succeeded by
    the time this runs, so a write problem must not turn it into an error."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(build_timeline_json(offsets))
    except OSError:
        pass


def prune_takes(directory: str, template: str, keep: int) -> list[str]:
    """Delete old takes matching this spec's own out-template. Opt-in only.

    Files are matched by the template's glob, so a take from a different spec (or
    any unrelated file) in the same directory is never touched. Best-effort
    housekeeping that never fails a take: it runs only after a recording has
    already succeeded, and returns only the paths actually deleted.
    """
    candidates = glob.glob(os.path.join(directory, out_glob(template)))
    doomed = select_prunable(candidates, keep)
    deleted = []
    for path in doomed:
        try:
            os.remove(path)
        except OSError:
            continue
        deleted.append(path)
    return deleted


class _Sequencer:
    """Drives launch order across frames without ever blocking the render loop.

    Each `tick(now)` advances the state machine at most one action: wait out the
    settle lead-in, gate on a signal (erroring on timeout), launch the next pane,
    honour its post-launch delay, wait for the verify predicate, then hold. It
    never sleeps — the frame loop paces itself — so frames keep flowing during
    every wait.
    """

    def __init__(self, spec: Spec, t0: float, launch) -> None:
        self._spec = spec
        self._steps = resolve_steps(spec)
        self._launch = launch
        self._step_i = 0
        self._next_action_at = t0 + SETTLE_S
        self._gate_deadline: float | None = None
        self._verify_deadline: float | None = None
        self._hold_until: float | None = None
        self._runtime_dir: str | None = None
        self.done = False

    def bind_runtime(self, runtime_dir: str) -> None:
        self._runtime_dir = runtime_dir

    def tick(self, now: float) -> None:
        if self.done or now < self._next_action_at:
            return
        rec = self._spec.recording

        if self._step_i < len(self._steps):
            step = self._steps[self._step_i]
            if step.wait_for and not os.path.exists(
                signal_path(self._runtime_dir, step.wait_for)
            ):
                if self._gate_deadline is None:
                    self._gate_deadline = now + rec.gate_timeout
                elif now >= self._gate_deadline:
                    raise RecordError(
                        f"timed out waiting for signal {step.wait_for!r}"
                    )
                return  # keep rendering frames while we wait for the gate
            self._gate_deadline = None
            self._launch(step)
            self._next_action_at = now + step.delay
            self._step_i += 1
            return

        # Every pane launched: wait out the verify predicate, then the hold.
        if self._verify_deadline is None and self._hold_until is None:
            if self._spec.verify.expect:
                self._verify_deadline = now + self._spec.verify.timeout
            else:
                self._hold_until = now + rec.hold
        if self._verify_deadline is not None:
            if not check_expectations(self._runtime_dir, self._spec.verify) or (
                now >= self._verify_deadline
            ):
                self._verify_deadline = None
                self._hold_until = now + rec.hold
        if self._hold_until is not None and now >= self._hold_until:
            self.done = True


def _slug(title: str) -> str:
    """A filename-safe slug of a pane title ('1  API SERVER' -> '1-api-server')."""
    s = re.sub(r"[^A-Za-z0-9]+", "-", title).strip("-").lower()
    return s or "pane"


def pane_out_path(out_path: str, index: int, title: str) -> str:
    """Per-pane output filename for `--split`: `rec.mov` + pane 0 'A' -> `rec-1-a.mov`."""
    root, ext = os.path.splitext(out_path)
    return f"{root}-{index + 1}-{_slug(title)}{ext}"


class _Target:
    """One encoder the frame loop feeds: its own geometry, ffmpeg child, and the
    pane indices it draws (all panes for the composite; exactly one when split)."""

    def __init__(self, out_path: str, log_path: str, geom, indices, fps, ffmpeg):
        self.out_path = out_path
        self.log_path = log_path
        self.geom = geom
        self.indices = indices
        args = build_encode_args(geom.width, geom.height, fps, out_path, ffmpeg)
        try:
            self._log = open(log_path, "wb")  # noqa: SIM115 - closed in close()
        except OSError as e:
            raise RecordError(f"could not open recorder log at {log_path!r}: {e}") from e
        try:
            self.proc = subprocess.Popen(
                args, stdin=subprocess.PIPE, stdout=self._log, stderr=self._log
            )
        except FileNotFoundError as e:
            self._log.close()
            raise RecordError(
                f"recorder not found: {ffmpeg!r}. Install ffmpeg and put it on PATH."
            ) from e
        except OSError as e:
            self._log.close()
            raise RecordError(f"could not start recorder: {e}") from e

    def write(self, all_snaps, palette, lf) -> None:
        snaps = [all_snaps[i] for i in self.indices]
        frame = render_frame(self.geom, snaps, palette, lf)
        try:
            self.proc.stdin.write(frame)
        except (BrokenPipeError, OSError) as e:
            raise RecordError(
                f"recorder stopped early; see log: {self.log_path} ({e})"
            ) from e

    def finish(self, offsets: dict[str, float]) -> None:
        if self.proc.stdin is not None:
            try:
                self.proc.stdin.close()
            except OSError:
                pass
        try:
            self.proc.wait(timeout=30)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        self._log.close()
        _write_timeline(f"{self.out_path}.timeline.json", offsets)


def run_take(
    spec: Spec,
    out_path: str,
    log_path: str,
    runtime_dir: str,
    ffmpeg: str = "ffmpeg",
    font_size: int = 16,
    font_path: str | None = None,
    theme: str = "dark",
    split: bool = False,
) -> list[str]:
    """Record one take: tile the panes, drive them in gated order, encode, tidy up.

    Returns the list of video files written. By default that's one composite
    `out_path`. With `split=True` each pane is rendered to its **own** independent
    video (`pane_out_path(...)`) — detachable windows the viewer can arrange
    freely — instead of the composite. Every output gets its own `.timeline.json`
    sidecar (identical offsets), so `annotate`/`narrate` work on any of them.

    Does NOT raise on a failed verify predicate — the .mov of a failed demo is
    worth keeping, so the CLI inspects `check_expectations` for the verdict and
    this only raises on an actual recording failure (ffmpeg missing/dead, no
    font). Timeline sidecars are always written on the way out.
    """
    os.makedirs(runtime_dir, exist_ok=True)
    rec = spec.recording
    n = len(spec.panes)

    lf = load_font(font_size, font_path)
    palette = get_theme(theme)

    targets: list[_Target] = []
    try:
        if split:
            # Each pane gets its own single-terminal frame and encoder.
            single = frame_geometry(
                solve_grid(spec.layout.mode, 1, rec.cols, rec.rows), lf.cell_w, lf.cell_h
            )
            for i, pane in enumerate(spec.panes):
                p_out = pane_out_path(out_path, i, pane.title)
                p_log = f"{p_out}.ffmpeg.log"
                targets.append(_Target(p_out, p_log, single, [i], rec.fps, ffmpeg))
        else:
            canvas = solve_grid(spec.layout.mode, n, rec.cols, rec.rows)
            geom = frame_geometry(canvas, lf.cell_w, lf.cell_h)
            targets.append(_Target(out_path, log_path, geom, list(range(n)), rec.fps, ffmpeg))
    except RecordError:
        for t in targets:  # tear down any encoders already started
            t.finish({})
        raise

    terminals: list[Terminal | None] = [None] * n
    panes_io = [None] * n
    offsets: dict[str, float] = {}
    watches = timeline_watches(spec, runtime_dir)

    t0 = time.monotonic()

    def launch(step) -> None:
        pane = spec.panes[step.index]
        env = dict(os.environ)
        env.update(pane_env(pane, runtime_dir, rec.step_delay))
        term = Terminal(pane.title, rec.cols, rec.rows)
        io = open_pane(pane.cmd, env, pane.cwd, rec.cols, rec.rows)
        terminals[step.index] = term
        panes_io[step.index] = io
        # Marker file whose first appearance times this pane's `pane:<title>` event.
        try:
            open(marker_path(runtime_dir, step.index), "w").close()
        except OSError:
            pass

    seq = _Sequencer(spec, t0, launch)
    seq.bind_runtime(runtime_dir)
    frame_interval = 1.0 / rec.fps
    frame_index = 0

    try:
        while not seq.done:
            now = time.monotonic()
            for i, io in enumerate(panes_io):
                if io is not None:
                    terminals[i].feed(io.read_output())
            for event, path in watches.items():
                if event not in offsets and os.path.exists(path):
                    offsets[event] = now - t0

            seq.tick(now)

            snaps = [t.snapshot() if t is not None else None for t in terminals]
            for target in targets:
                target.write(snaps, palette, lf)

            frame_index += 1
            sleep = (t0 + frame_index * frame_interval) - time.monotonic()
            if sleep > POLL_S:
                time.sleep(sleep)
    finally:
        for target in targets:
            target.finish(offsets)
        for io in panes_io:
            if io is not None:
                io.terminate()
                io.close()

    for target in targets:
        if target.proc.returncode not in (0, None):
            raise RecordError(
                f"ffmpeg exited {target.proc.returncode}; see log: {target.log_path}"
            )
    return [t.out_path for t in targets]
