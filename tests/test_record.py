import os
import time
from pathlib import Path
from shutil import which

import pytest

from pocyeah.record import RecordError, prune_takes

# ---------------------------------------------------------------------------
# prune_takes — unchanged behaviour, still the opt-in housekeeping contract.
# ---------------------------------------------------------------------------


def test_prune_takes_deletes_the_oldest(tmp_path):
    for stamp in ("20260721-090000", "20260721-143000", "20260722-010000"):
        (tmp_path / f"rec-{stamp}.mov").write_text("x")
    deleted = prune_takes(str(tmp_path), "rec-{stamp}.mov", keep=1)
    assert [Path(p).name for p in deleted] == [
        "rec-20260721-090000.mov",
        "rec-20260721-143000.mov",
    ]
    assert sorted(p.name for p in tmp_path.iterdir()) == ["rec-20260722-010000.mov"]


def test_prune_takes_keeps_everything_by_default(tmp_path):
    (tmp_path / "rec-20260721-090000.mov").write_text("x")
    assert prune_takes(str(tmp_path), "rec-{stamp}.mov", keep=0) == []
    assert len(list(tmp_path.iterdir())) == 1


def test_prune_takes_ignores_unrelated_files(tmp_path):
    (tmp_path / "rec-20260721-090000.mov").write_text("x")
    (tmp_path / "rec-20260722-010000.mov").write_text("x")
    (tmp_path / "important.mov").write_text("x")
    (tmp_path / "notes.txt").write_text("x")
    prune_takes(str(tmp_path), "rec-{stamp}.mov", keep=1)
    names = sorted(p.name for p in tmp_path.iterdir())
    assert names == ["important.mov", "notes.txt", "rec-20260722-010000.mov"]


def test_prune_takes_continues_past_a_failed_removal(tmp_path, monkeypatch):
    stamps = ("20260721-090000", "20260721-143000", "20260722-010000")
    for stamp in stamps:
        (tmp_path / f"rec-{stamp}.mov").write_text("x")
    doomed_but_unremovable = str(tmp_path / "rec-20260721-090000.mov")

    real_remove = os.remove

    def flaky_remove(path):
        if path == doomed_but_unremovable:
            raise PermissionError("simulated permission failure")
        real_remove(path)

    monkeypatch.setattr(os, "remove", flaky_remove)
    deleted = prune_takes(str(tmp_path), "rec-{stamp}.mov", keep=1)
    assert deleted == [str(tmp_path / "rec-20260721-143000.mov")]
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == ["rec-20260721-090000.mov", "rec-20260722-010000.mov"]


def test_prune_takes_treats_an_already_vanished_file_as_benign(tmp_path, monkeypatch):
    stamps = ("20260721-090000", "20260721-143000", "20260722-010000")
    for stamp in stamps:
        (tmp_path / f"rec-{stamp}.mov").write_text("x")
    vanished = str(tmp_path / "rec-20260721-090000.mov")
    os.remove(vanished)

    real_remove = os.remove

    def vanishing_remove(path):
        if path == vanished:
            raise FileNotFoundError(f"already gone: {path}")
        real_remove(path)

    monkeypatch.setattr(os, "remove", vanishing_remove)
    deleted = prune_takes(str(tmp_path), "rec-{stamp}.mov", keep=1)
    assert deleted == [str(tmp_path / "rec-20260721-143000.mov")]
    remaining = sorted(p.name for p in tmp_path.iterdir())
    assert remaining == ["rec-20260722-010000.mov"]


# ---------------------------------------------------------------------------
# timeline sidecar — the record/annotate contract, unchanged.
# ---------------------------------------------------------------------------


def test_write_timeline_includes_start_and_events(tmp_path):
    from pocyeah.record import _write_timeline
    from pocyeah.subtitles import load_timeline

    path = tmp_path / "out.mov.timeline.json"
    _write_timeline(str(path), {"server_ready": 3.5, "pane:1  S": 2.0})
    tl = load_timeline(path.read_text())
    assert tl == {"start": 0.0, "pane:1  S": 2.0, "server_ready": 3.5}


def test_write_timeline_is_best_effort_on_bad_path(tmp_path):
    from pocyeah.record import _write_timeline

    _write_timeline("/nonexistent-dir-xyz/out.timeline.json", {"sig": 1.0})  # no raise


# ---------------------------------------------------------------------------
# _Sequencer — the pure-ish launch/gate/verify/hold state machine.
# ---------------------------------------------------------------------------


def _spec(panes, **rec):
    from pocyeah.spec import Layout, Recording, Spec

    return Spec(
        recording=Recording(**rec),
        layout=Layout(mode="columns"),
        panes=tuple(panes),
    )


def test_sequencer_launches_after_settle_then_holds(tmp_path):
    from pocyeah.record import SETTLE_S, _Sequencer
    from pocyeah.spec import Pane

    spec = _spec([Pane(title="A", cmd="echo a")], hold=0.0)
    launched = []
    seq = _Sequencer(spec, t0=0.0, launch=lambda step: launched.append(step.index))
    seq.bind_runtime(str(tmp_path))

    seq.tick(now=0.0)  # inside the settle window: nothing yet
    assert launched == [] and not seq.done

    seq.tick(now=SETTLE_S + 0.01)  # settle over: launch the only pane
    assert launched == [0]

    seq.tick(now=SETTLE_S + 0.02)  # all launched, hold=0 -> done
    assert seq.done


def test_sequencer_gates_second_pane_on_a_signal(tmp_path):
    from pocyeah.record import SETTLE_S, _Sequencer
    from pocyeah.spec import Pane

    spec = _spec(
        [
            Pane(title="A", cmd="echo a", signals=("go",)),
            Pane(title="B", cmd="echo b", gate_on="go"),
        ],
        hold=0.0,
    )
    launched = []
    seq = _Sequencer(spec, t0=0.0, launch=lambda step: launched.append(step.index))
    seq.bind_runtime(str(tmp_path))

    t = SETTLE_S + 0.01
    seq.tick(now=t)  # launches pane A
    assert launched == [0]
    seq.tick(now=t + 0.01)  # pane B gated on "go", which does not exist yet
    assert launched == [0]

    (tmp_path / "go").write_text("")  # the signal fires
    seq.tick(now=t + 0.02)  # now pane B can launch
    assert launched == [0, 1]


def test_sequencer_raises_on_gate_timeout(tmp_path):
    from pocyeah.record import SETTLE_S, _Sequencer
    from pocyeah.spec import Pane

    spec = _spec(
        [Pane(title="A", cmd="true", gate_on="never")], hold=0.0, gate_timeout=5.0
    )
    seq = _Sequencer(spec, t0=0.0, launch=lambda step: None)
    seq.bind_runtime(str(tmp_path))

    t = SETTLE_S + 0.01
    seq.tick(now=t)  # arms the gate deadline (t + 5.0)
    seq.tick(now=t + 1.0)  # still waiting, no error
    with pytest.raises(RecordError, match="never"):
        seq.tick(now=t + 6.0)  # past the deadline


# ---------------------------------------------------------------------------
# run_take — a real, headless, cross-platform recording (needs ffmpeg + deps).
# ---------------------------------------------------------------------------

_HAVE_STACK = which("ffmpeg") is not None
try:  # the recorder extra
    import PIL  # noqa: F401
    import pyte  # noqa: F401
except ImportError:  # pragma: no cover
    _HAVE_STACK = False


@pytest.mark.skipif(not _HAVE_STACK, reason="needs ffmpeg + pocyeah[record]")
def test_run_take_produces_a_playable_mov_and_timeline(tmp_path):
    from pocyeah.record import run_take
    from pocyeah.spec import Pane

    spec = _spec(
        [Pane(title="ONE", cmd="printf 'hello from pocyeah\\n'")],
        fps=10,
        cols=40,
        rows=6,
        hold=0.3,
    )
    out = tmp_path / "take.mov"
    run_take(
        spec,
        out_path=str(out),
        log_path=str(tmp_path / "take.log"),
        runtime_dir=str(tmp_path / "rt"),
        font_size=14,
    )
    assert out.exists() and out.stat().st_size > 0
    tl = tmp_path / "take.mov.timeline.json"
    assert tl.exists()
    from pocyeah.subtitles import load_timeline

    timeline = load_timeline(tl.read_text())
    assert timeline["start"] == 0.0
    assert "pane:ONE" in timeline  # the pane-open event was captured


def test_pane_out_path_slugifies_title():
    from pocyeah.record import pane_out_path

    # filename is <root>-<pane number>-<title slug><ext>
    assert pane_out_path("/d/rec.mov", 0, "API SERVER") == "/d/rec-1-api-server.mov"
    assert pane_out_path("/d/rec.mov", 2, "② ATTACKER!") == "/d/rec-3-attacker.mov"


@pytest.mark.skipif(not _HAVE_STACK, reason="needs ffmpeg + pocyeah[record]")
def test_run_take_split_writes_one_video_per_pane(tmp_path):
    from pocyeah.record import pane_out_path, run_take
    from pocyeah.spec import Pane
    from pocyeah.subtitles import load_timeline

    spec = _spec(
        [
            Pane(title="ONE", cmd='printf "first\\n"; : > "$DEMO_RUNTIME_DIR/go"',
                 signals=("go",)),
            Pane(title="TWO", cmd='printf "second\\n"', gate_on="go"),
        ],
        fps=10,
        cols=30,
        rows=5,
        hold=0.3,
    )
    out = tmp_path / "take.mov"
    written = run_take(
        spec,
        out_path=str(out),
        log_path=str(tmp_path / "take.log"),
        runtime_dir=str(tmp_path / "rt"),
        font_size=14,
        split=True,
    )
    # one detachable video per pane, no composite
    assert not out.exists()
    assert written == [
        pane_out_path(str(out), 0, "ONE"),
        pane_out_path(str(out), 1, "TWO"),
    ]
    for p in written:
        assert os.path.exists(p) and os.path.getsize(p) > 0
        tl = load_timeline((Path(p).parent / (Path(p).name + ".timeline.json")).read_text())
        assert tl["start"] == 0.0  # each pane video carries its own sidecar


@pytest.mark.skipif(not _HAVE_STACK, reason="needs ffmpeg + pocyeah[record]")
def test_run_take_reports_a_missing_ffmpeg(tmp_path):
    from pocyeah.record import run_take
    from pocyeah.spec import Pane

    spec = _spec([Pane(title="A", cmd="true")], fps=10, cols=20, rows=4, hold=0.0)
    with pytest.raises(RecordError, match="not found"):
        run_take(
            spec,
            out_path=str(tmp_path / "t.mov"),
            log_path=str(tmp_path / "t.log"),
            runtime_dir=str(tmp_path / "rt"),
            ffmpeg="definitely-not-a-real-ffmpeg-xyz",
        )
