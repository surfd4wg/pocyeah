import os

import pytest

from pocyeah.narration import Section
from pocyeah.spec import Tts
from pocyeah.synth import Clip, SynthError, synthesize


def test_require_engine_raises_actionable_error_when_not_installed(monkeypatch):
    # Force the lazy SDK import to fail so the hint is asserted regardless of
    # whether the elevenlabs SDK happens to be installed in this environment.
    import builtins

    from pocyeah import synth

    real_import = builtins.__import__

    def _no_elevenlabs(name, *args, **kwargs):
        if name.startswith("elevenlabs"):
            raise ImportError("no elevenlabs")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_elevenlabs)
    with pytest.raises(SynthError) as exc:
        synth._require_engine()
    assert "pocyeah[tts]" in str(exc.value)


class _FakeConvert:
    """Records each convert() call and returns MP3-like byte chunks."""

    def __init__(self, calls):
        self._calls = calls

    def convert(self, **kwargs):
        self._calls.append(kwargs)
        yield b"ID3fake"
        yield b"audio-bytes"


class _FakeClient:
    def __init__(self, api_key):
        self.api_key = api_key
        self.text_to_speech = _FakeConvert(_FakeClient.calls)

    calls: list[dict] = []


def _fake_voice_settings(**kwargs):
    return kwargs


def test_synthesize_builds_client_calls_convert_and_probes(tmp_path, monkeypatch):
    from pocyeah import synth

    _FakeClient.calls = []
    made_clients: list[str] = []

    def _fake_client(api_key):
        made_clients.append(api_key)
        return _FakeClient(api_key)

    monkeypatch.setattr(
        synth, "_require_engine", lambda: (_fake_client, _fake_voice_settings)
    )
    # Fake ffprobe: 2.5s for the first clip, 1.0s for the second.
    durations = iter([2.5, 1.0])
    monkeypatch.setattr(synth, "_probe_duration", lambda path, ffprobe: next(durations))

    sections = [
        Section(on="start", text="One.", offset=0.0, slot=3.0),
        Section(on="s2", text="Two.", offset=3.0, slot=float("inf")),
    ]
    tts = Tts(voice_id="VID", model_id="MID", speed=1.2, seed=7)
    clips = synthesize(sections, tts, str(tmp_path), api_key="sk_test")

    assert made_clients == ["sk_test"]  # one client, built with the resolved key
    calls = _FakeClient.calls
    assert [c["text"] for c in calls] == ["One.", "Two."]
    assert all(c["voice_id"] == "VID" for c in calls)
    assert all(c["model_id"] == "MID" for c in calls)
    assert all(c["seed"] == 7 for c in calls)
    assert all(c["voice_settings"] == {"speed": 1.2} for c in calls)

    assert all(isinstance(c, Clip) for c in clips)
    assert [c.duration for c in clips] == [2.5, 1.0]
    for c in clips:
        assert os.path.exists(c.path)
        assert c.path.endswith(".mp3")
        with open(c.path, "rb") as f:
            assert f.read() == b"ID3fakeaudio-bytes"


def test_synthesize_routes_to_local_when_no_api_key(tmp_path, monkeypatch):
    from pocyeah import synth

    routed = {}
    monkeypatch.setattr(
        synth, "_synthesize_local",
        lambda sections, tts, out_dir: routed.setdefault("local", True) or [],
    )
    synth.synthesize([], Tts(), str(tmp_path), api_key=None)
    assert routed == {"local": True}


def test_local_fallback_names_install_extra_when_engine_missing(monkeypatch, tmp_path):
    # Force the lazy import to fail so the message is asserted regardless of
    # whether piper-tts happens to be installed in this environment.
    from pocyeah import synth

    import builtins

    real_import = builtins.__import__

    def _no_piper(name, *args, **kwargs):
        if name.startswith("piper"):
            raise ImportError("no piper")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_piper)
    with pytest.raises(SynthError) as exc:
        synth.synthesize([], Tts(), str(tmp_path), api_key=None)
    assert "pocyeah[tts-local]" in str(exc.value)


def test_local_synthesis_writes_wav_clips_with_measured_durations(tmp_path, monkeypatch):
    """Exercise the Piper local path with a fake voice that writes a real WAV,
    proving _synthesize_local wires synthesize_wav + duration reading correctly.
    """
    import wave

    from pocyeah import synth

    class _FakeSynConfig:
        def __init__(self, length_scale=None):
            self.length_scale = length_scale

    class _FakeVoice:
        seen: list = []

        def synthesize_wav(self, text, wf, syn_config=None):
            _FakeVoice.seen.append((text, syn_config.length_scale))
            # write ~0.5s of silence at 22050 Hz, 16-bit mono
            wf.setnchannels(1)
            wf.setsampwidth(2)
            wf.setframerate(22050)
            wf.writeframes(b"\x00\x00" * 11025)

    monkeypatch.setattr(
        synth, "_require_local_engine", lambda: (_FakeVoice, _FakeSynConfig, None)
    )
    monkeypatch.setattr(synth, "_resolve_local_model", lambda PV, dl: _FakeVoice())

    sections = [
        Section(on="start", text="One.", offset=0.0, slot=5.0),
        Section(on="s2", text="Two.", offset=5.0, slot=float("inf")),
    ]
    clips = synth._synthesize_local(sections, Tts(speed=2.0), str(tmp_path))

    assert [c.path.endswith(".wav") for c in clips] == [True, True]
    for c in clips:
        assert os.path.exists(c.path)
        assert abs(c.duration - 0.5) < 0.01  # read from the WAV header
        with wave.open(c.path, "rb") as w:
            assert w.getframerate() == 22050
    # speed 2.0 -> length_scale 0.5 (faster => shorter)
    assert all(ls == 0.5 for _, ls in _FakeVoice.seen)
    assert [t for t, _ in _FakeVoice.seen] == ["One.", "Two."]


def test_synthesize_wraps_convert_failure_in_syntherror(tmp_path, monkeypatch):
    from pocyeah import synth

    class _BoomConvert:
        def convert(self, **kwargs):
            raise RuntimeError("401 unauthorized")

    class _BoomClient:
        def __init__(self, api_key):
            self.text_to_speech = _BoomConvert()

    monkeypatch.setattr(
        synth, "_require_engine", lambda: (_BoomClient, _fake_voice_settings)
    )
    sections = [Section(on="start", text="One.", offset=0.0, slot=float("inf"))]

    with pytest.raises(SynthError, match="synthesis failed"):
        synthesize(sections, Tts(), str(tmp_path), api_key="sk_test")
