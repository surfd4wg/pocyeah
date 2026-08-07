"""TTS synthesis (N14/A7.4). Effect edge — NOT pure.

Two backends behind one `synthesize()`:

* **ElevenLabs** (cloud, preferred) when an API key is resolved — higher quality.
* **on-device Piper** (local fallback) when no key is found — no network at
  synth time, cross-platform (Linux/Windows/macOS), fast, and deterministic.

`synthesize()` picks the backend from whether `api_key` is truthy. Each engine
is imported LAZILY and nowhere else, so the core package keeps `dependencies = []`
and runs fine without the opt-in extras (`pocyeah[tts]` for ElevenLabs,
`pocyeah[tts-local]` for Piper). The API key is resolved by the caller
(env var or a project `.env`) and passed in — this module never reads credentials.

The default Piper voice is downloaded once to a per-user cache on first use;
`$POCYEAH_PIPER_MODEL` overrides it with a path to a local `.onnx` model.
"""
from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass

from pocyeah.narration import Section
from pocyeah.spec import Tts

# ElevenLabs returns MP3 at this bitrate/samplerate; ffmpeg reads it directly in
# the mix step and ffprobe reads its duration. mp3 is self-describing, so the
# mixing argv needs no per-input format flags.
_OUTPUT_FORMAT = "mp3_44100_128"

# The on-device fallback voice. The Tts block's voice_id/model_id are ElevenLabs
# identifiers, so the local Piper engine uses its own fixed model; only `speed`
# carries over (as a length scale). `$POCYEAH_PIPER_MODEL` overrides the model.
_LOCAL_MODEL = "en_US-lessac-medium"
_MODEL_ENV = "POCYEAH_PIPER_MODEL"


class SynthError(Exception):
    """Raised when the TTS engine is missing or a synthesis call fails."""


@dataclass(frozen=True)
class Clip:
    """A synthesized narration clip on disk plus its measured duration."""

    path: str
    duration: float


def synthesize(
    sections: list[Section], tts: Tts, out_dir: str, api_key: str | None,
    ffprobe: str = "ffprobe",
) -> list[Clip]:
    """Render one clip per section into `out_dir`, returned in section order.

    Uses ElevenLabs when `api_key` is truthy, otherwise falls back to the
    on-device Piper engine. Raises SynthError if the chosen engine is
    absent or a synthesis call fails.
    """
    if api_key:
        return _synthesize_elevenlabs(sections, tts, out_dir, api_key, ffprobe)
    return _synthesize_local(sections, tts, out_dir)


# --- ElevenLabs (cloud) -----------------------------------------------------

def _require_engine():
    """Import the ElevenLabs SDK lazily; on failure raise an actionable error.

    Returns `(ElevenLabs, VoiceSettings)`. Isolated so tests can monkeypatch it
    with fakes instead of installing the SDK or hitting the network.
    """
    try:
        from elevenlabs import VoiceSettings
        from elevenlabs.client import ElevenLabs
    except ImportError as e:
        raise SynthError(
            "ElevenLabs SDK not installed. Install it with: pip install 'pocyeah[tts]'"
        ) from e
    return ElevenLabs, VoiceSettings


def _probe_duration(path: str, ffprobe: str = "ffprobe") -> float:
    """Real duration of an audio file in seconds, via ffprobe.

    Raises SynthError if ffprobe is missing or cannot read the file — the
    overlap guard depends on this number being accurate.
    """
    try:
        result = subprocess.run(
            [ffprobe, "-v", "error", "-show_entries", "format=duration",
             "-of", "default=noprint_wrappers=1:nokey=1", path],
            capture_output=True, text=True,
        )
    except FileNotFoundError as e:
        raise SynthError(
            f"ffprobe not found: {ffprobe!r}. Install it (brew install ffmpeg)"
        ) from e
    if result.returncode != 0:
        raise SynthError(f"ffprobe failed on {path!r}: {result.stderr.strip()}")
    try:
        return float(result.stdout.strip())
    except ValueError as e:
        raise SynthError(f"ffprobe gave no duration for {path!r}") from e


def _synthesize_elevenlabs(
    sections: list[Section], tts: Tts, out_dir: str, api_key: str, ffprobe: str,
) -> list[Clip]:
    """Render each section with ElevenLabs text_to_speech.convert.

    Builds one client and calls convert per section with a pinned `seed`
    (best-effort reproducibility) and the configured voice/model/speed, then
    measures each clip's real duration with ffprobe.
    """
    ElevenLabs, VoiceSettings = _require_engine()
    client = ElevenLabs(api_key=api_key)
    settings = VoiceSettings(speed=tts.speed)

    clips: list[Clip] = []
    for i, section in enumerate(sections):
        try:
            audio = client.text_to_speech.convert(
                text=section.text,
                voice_id=tts.voice_id,
                model_id=tts.model_id,
                output_format=_OUTPUT_FORMAT,
                voice_settings=settings,
                seed=tts.seed,
            )
        except Exception as e:  # noqa: BLE001 - surface any API failure uniformly
            raise SynthError(f"synthesis failed for {section.text!r}: {e}") from e
        path = os.path.join(out_dir, f"clip-{i:03d}.mp3")
        with open(path, "wb") as f:
            for chunk in audio:
                f.write(chunk)
        clips.append(Clip(path=path, duration=_probe_duration(path, ffprobe)))
    return clips


# --- Piper (cross-platform on-device fallback) ------------------------------

def _require_local_engine():
    """Import the on-device Piper engine lazily; on failure raise an actionable
    error. Returns `(PiperVoice, SynthesisConfig, download_voice)`.
    """
    try:
        from piper import PiperVoice, SynthesisConfig
        from piper.download_voices import download_voice
    except ImportError as e:
        raise SynthError(
            "No ElevenLabs API key and the on-device engine is not installed. "
            "Set $ELEVENLABS_API_KEY, or install the fallback with: "
            "pip install 'pocyeah[tts-local]'"
        ) from e
    return PiperVoice, SynthesisConfig, download_voice


def _cache_dir() -> str:
    """Per-user cache for downloaded Piper voices (XDG on POSIX, LOCALAPPDATA on
    Windows), created on demand."""
    base = (
        os.environ.get("XDG_CACHE_HOME")
        or os.environ.get("LOCALAPPDATA")
        or os.path.join(os.path.expanduser("~"), ".cache")
    )
    path = os.path.join(base, "pocyeah", "piper")
    os.makedirs(path, exist_ok=True)
    return path


def _resolve_local_model(PiperVoice, download_voice):
    """Load the local voice: an explicit `$POCYEAH_PIPER_MODEL` path if set,
    otherwise the default voice, downloaded to the per-user cache on first use."""
    override = os.environ.get(_MODEL_ENV)
    if override:
        if not os.path.exists(override):
            raise SynthError(f"${_MODEL_ENV} points at a missing model: {override!r}")
        return PiperVoice.load(override)

    import pathlib

    cache = _cache_dir()
    model_path = os.path.join(cache, f"{_LOCAL_MODEL}.onnx")
    if not os.path.exists(model_path):
        try:
            download_voice(_LOCAL_MODEL, pathlib.Path(cache))
        except Exception as e:  # noqa: BLE001 - network/download failures vary
            raise SynthError(
                f"could not download the default Piper voice {_LOCAL_MODEL!r}: {e}. "
                f"Set ${_MODEL_ENV} to a local .onnx model to synthesize offline."
            ) from e
    return PiperVoice.load(model_path)


def _wav_duration(path: str) -> float:
    """Duration of a PCM WAV in seconds, from its own header (no ffprobe)."""
    import wave

    with wave.open(path, "rb") as w:
        frames = w.getnframes()
        rate = w.getframerate()
    return frames / rate if rate else 0.0


def _synthesize_local(sections: list[Section], tts: Tts, out_dir: str) -> list[Clip]:
    """Render each section with the on-device Piper engine.

    Loads the voice once. The Tts voice_id/model_id are ElevenLabs identifiers,
    so this fallback uses its own model; `speed` maps to Piper's length scale
    (higher speed => shorter audio). Output is a self-describing WAV, so its
    duration is read straight from the header.
    """
    PiperVoice, SynthesisConfig, download_voice = _require_local_engine()
    try:
        voice = _resolve_local_model(PiperVoice, download_voice)
    except SynthError:
        raise
    except Exception as e:  # noqa: BLE001 - surface any load failure uniformly
        raise SynthError(f"could not load local TTS voice: {e}") from e

    # Piper's length_scale stretches time: >1 is slower. Invert `speed` so a
    # spec speed of 1.2 (20% faster) shortens the clip, matching ElevenLabs.
    syn = SynthesisConfig(length_scale=(1.0 / tts.speed if tts.speed else 1.0))

    clips: list[Clip] = []
    for i, section in enumerate(sections):
        path = os.path.join(out_dir, f"clip-{i:03d}.wav")
        try:
            import wave

            with wave.open(path, "wb") as wf:
                voice.synthesize_wav(section.text, wf, syn_config=syn)
        except Exception as e:  # noqa: BLE001 - surface any synth failure uniformly
            raise SynthError(f"synthesis failed for {section.text!r}: {e}") from e
        clips.append(Clip(path=path, duration=_wav_duration(path)))
    return clips
