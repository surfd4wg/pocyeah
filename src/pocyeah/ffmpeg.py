"""Pure ffmpeg CLI construction for the portable recorder (the pure half of N9).

The recorder renders every frame itself (an in-process terminal emulator drawn
to pixels — see frame.py) and pipes raw RGB into ffmpeg over stdin, so capture
is identical on Linux, Windows and macOS and needs no screen-recording
permission, no display server, and no per-host capture-device discovery.

This module only *builds the argv*; record.py owns the child process and the
pipe. Keeping the argv here keeps it unit-testable with no ffmpeg present.
"""
from __future__ import annotations

# The recorder feeds frames as `rgb24` (3 bytes/pixel, no padding) at a fixed
# size and rate. libx264 + yuv420p is the widely-playable baseline the old
# avfoundation path also targeted; `-` reads the raw stream from stdin.
def build_encode_args(
    width: int,
    height: int,
    fps: int,
    out_path: str,
    ffmpeg: str = "ffmpeg",
) -> list[str]:
    """Assemble the argv that encodes a raw RGB frame stream from stdin.

    `width`/`height` are the exact pixel size of every frame the renderer emits;
    libx264 requires even dimensions under yuv420p, so the caller (render.py)
    guarantees both are even. The input is silent — narration is mixed on later
    by `narrate`, matching the old pipeline's contract.
    """
    if width <= 0 or height <= 0:
        raise ValueError(f"frame size must be positive, got {width}x{height}")
    if width % 2 or height % 2:
        raise ValueError(f"frame size must be even for yuv420p, got {width}x{height}")
    if fps <= 0:
        raise ValueError(f"fps must be positive, got {fps}")
    return [
        ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "rawvideo",
        "-pix_fmt",
        "rgb24",
        "-s",
        f"{width}x{height}",
        "-framerate",
        str(fps),
        "-i",
        "-",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        "-y",
        out_path,
    ]
