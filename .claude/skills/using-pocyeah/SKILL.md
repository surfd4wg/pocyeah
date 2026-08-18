---
name: using-pocyeah
description: Use when recording, captioning, or narrating a proof-of-concept demo with this repo's pocyeah / pocyeah CLI — authoring or running a demo.toml, producing a screen-recording .mov take, or adding burned-in subtitles or spoken narration to a take.
---

# Using PocYeah

Spec-driven CLI (`pocyeah`) that turns one `demo.toml` into a
narrated, multi-terminal screen-recording. Run everything with `uv run pocyeah …`
from the repo (or a global `pocyeah` if installed).

**Core model:** a cheap headless inner loop (`validate`, `dryrun`) you iterate on,
then **one** expensive render step (`record`), then re-runnable post-production
(`annotate`, `narrate`). Captions anchor to **demo events**, not wall-clock time —
which is why the pipeline works the way it does.

`record` is **cross-platform** (Linux, Windows, macOS): it runs each pane's
command in a real pseudo-terminal, renders the terminals to video frames itself,
and pipes them to ffmpeg. No Terminal.app, no screen-recording permission, no
display server — it works headless, including in CI.

## First move: `pocyeah explain`

Run `uv run pocyeah explain` for the authoritative, always-current `demo.toml` schema.
**Do not guess TOML fields and do not read the source to answer schema or usage
questions** — `explain` and this skill are the reference. `pocyeah scaffold <dir>`
writes a working starter demo (create-only; never overwrites).

## The pipeline

| Command | Runs where | Needs | Emits |
|---|---|---|---|
| `validate <spec>` | anywhere | — | schema OK + narration-length warnings |
| `dryrun <spec>` | anywhere (CI too) | — | PASS/FAIL: runs roles headless, asserts `[verify]` |
| `record <spec>` | anywhere (Linux/Windows/macOS) | ffmpeg + `pocyeah[record]` (pyte, Pillow) | `<out>.mov` **and** `<out>.mov.timeline.json` (or, with `--split`, one detachable video per pane) |
| `annotate <spec> <mov>` | anywhere | ffmpeg | `<mov>-captioned.mov` (burns `[[annotation]]` + `[[overlay]]`) |
| `narrate <spec> <mov>` | anywhere | ffmpeg + ffprobe + TTS | `<mov>-narrated.mov` (speaks `[[annotation]]`) |

## The one rule that isn't obvious: the timeline sidecar is the contract

`record` writes two files: the `.mov` **and** a `<mov>.timeline.json` sidecar
mapping each event to its video offset. `annotate` and `narrate` **require that
sidecar sitting next to their input `.mov`** — it's how captions land on the right
frames.

**You cannot meaningfully annotate/narrate a video `record` didn't produce**
(e.g. a QuickTime capture). No sidecar → both commands hard-error. Hand-authoring
a sidecar is possible but fragile and off the intended path; the right move is to
re-record with `pocyeah record` so events and offsets are real.

Re-wording is cheap: edit `[[annotation]]` text and re-run `annotate`/`narrate`
against the **same** take — no re-record needed.

## Iterate cheap, record once

Do NOT jump straight to `record`. The loop is:

1. `validate` — instant schema + caption-length check.
2. `dryrun` — runs the actual roles headless and exits non-zero unless `[verify]`
   holds. **This is how you confirm the PoC works before paying for a screen take.**
   Iterate here until it PASSes.
3. `record` — the one expensive step. It runs each pane in a real PTY, renders
   the terminals to video, and **runs the demo for real** (a real-exploit PoC will
   genuinely fire). Only run it once the dryrun is green.

## Captioned AND narrated (the chain)

`annotate` and `narrate` each consume the original take independently. To get
**both** burned captions and spoken narration in one file, chain them — **order
matters**:

```bash
uv run pocyeah record <spec>                         # -> <stamp>.mov + <stamp>.mov.timeline.json
# record's output is timestamped and the dir fills with derived files, so grab the
# fresh raw take by name, excluding derived ones, right after recording:
TAKE=$(ls -t <demo-dir>/*-*.mov | grep -Ev '(captioned|narrated)' | head -1)
uv run pocyeah annotate <spec> "$TAKE"               # -> $TAKE-captioned.mov  (captions in pixels)
cp "$TAKE.timeline.json" "${TAKE%.mov}-captioned.mov.timeline.json"  # narrate needs a sidecar beside ITS input
uv run pocyeah narrate <spec> "${TAKE%.mov}-captioned.mov"   # -> ...-captioned-narrated.mov
```

Annotate **first**: narrate copies the video stream (`-c:v copy`), so burned-in
captions survive, and it adds the audio. Narrating first then annotating re-encodes
video and does not reliably preserve the narration audio. `annotate` writes no
sidecar, so you must copy the original's next to the `-captioned.mov` (step 3).

## `record` and `narrate` requirements

- **`record`**: `ffmpeg` on PATH + the recorder extra (`pip install 'pocyeah[record]'`
  — pyte + Pillow, plus pywinpty on Windows). No OS permissions, no display server;
  frame size is driven by `[recording] cols`/`rows`/`font_size` and `theme`.
- **`narrate`**: `ffmpeg` + `ffprobe`. Uses ElevenLabs when a key is present
  (`$ELEVENLABS_API_KEY`, or a `.env` beside the spec), else falls back to the
  cross-platform on-device engine, Piper (`pocyeah[tts-local]`). Pass
  `uv run --extra tts pocyeah narrate …` to keep the cloud backend available under `uv run`.
  Piper downloads its default voice once to a per-user cache on first use; set
  `$POCYEAH_PIPER_MODEL` to a local `.onnx` model to synthesize fully offline.
- **Env-key quirk:** a key exported only in a shell profile (`~/.zshrc`,
  `~/.bashrc`) is invisible to a non-interactive shell, so `narrate` silently falls
  back to on-device TTS. If the key lives in your profile, run it through an
  interactive shell, or drop a `.env` beside the spec.

## Common mistakes

| Mistake | Reality |
|---|---|
| Reading `src/` to answer a usage/schema question | Run `pocyeah explain`; use this skill. Source-diving is wasted work. |
| `validate → record`, skipping `dryrun` | `dryrun` proves the PoC works headlessly and free. Iterate there first. |
| `annotate`/`narrate` on a hand-recorded `.mov` | No `<mov>.timeline.json` → hard error. Only `record` produces a real one. |
| Narrate first, then annotate | Annotate re-encodes video and won't reliably keep the narration. Annotate → narrate. |
| Forgetting the sidecar copy when chaining | `narrate` needs `<its-input>.timeline.json`; `annotate` doesn't write one. |
| Re-running `record` casually | `[recording] keep` prunes by glob and can delete derived `-captioned`/`-narrated` files too. Grab the fresh `.mov` path right after the take. |

## Safety

A `demo.toml` executes arbitrary commands on your host as you — `dryrun` and
`record` run the panes' `cmd`s. Only run specs you wrote or have read. For a real
exploit PoC, prefer `dryrun` or `record` inside a throwaway container or VM.
See the README's "Running demos safely".
