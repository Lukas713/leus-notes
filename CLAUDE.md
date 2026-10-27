# leus-notes — Developer Guide

Personal tool: record a call on this Linux machine (PipeWire), transcribe it
locally (faster-whisper on the RTX 4090), separate speakers (pyannote), and
have Claude write English meeting notes through `claude -p` on the user's
**Claude subscription** — never the API.

User-facing docs: `README.md`. Tickets: `docs/tickets/meeting-notes-tool.md`,
`docs/tickets/share-notes-google-docs.md`.

## Hard rules

- **No API billing.** Before every notes call `require_subscription()` runs
  `claude auth status` and refuses unless `authMethod` is `claude.ai`. The call
  itself is `claude -p --safe-mode …` with every `ANTHROPIC_*` and
  `CLAUDE_CODE_USE_*` variable stripped (API key, base URL, Bedrock/Vertex).
  Never use `--bare` (it ignores OAuth and requires an API key).
- **Everything stays in this folder.** The launcher points `HF_HOME`,
  `TORCH_HOME`, `MPLCONFIGDIR`, `CUDA_CACHE_PATH` into the project and
  `install.py` uses `pip --no-cache-dir`. The Google OAuth client and token
  live in `google/` (0700, token 0600, git-ignored). The only write outside is
  the `~/.local/bin/leus-notes` symlink.
- **Notes leave the machine only on request.** Google Drive gets a meeting's
  notes (never transcript or audio) only after `leus-notes share` for that
  meeting. The automatic refresh after `names` / `process --notes` only updates
  an existing, live Doc — it never creates one and never opens a login. Scope is
  `drive.file`: the tool sees only the folder and Docs it created.
- **Audio is kept whenever something failed** (`meta.keep_audio_reason`), so
  the meeting can be reprocessed. It is deleted after the first successful
  notes only when `audio.keep_days = 0`.
- Code style: no descriptive comments; self-explanatory names and type hints.

## Layout

| Path | Role |
|---|---|
| `leus-notes` | Python launcher (entry point, symlinked into `~/.local/bin`). Re-execs itself with `.venv/bin/python` after setting `LD_LIBRARY_PATH` to the venv's `nvidia/*/lib` dirs — CTranslate2 needs the CUDA libs on the path *before* the process starts. |
| `install.py` | Stdlib-only installer (runs with system Python). Reuses `leus_notes.doctor` checks, which only import heavy libraries lazily. |
| `src/leus_notes/cli.py` | argparse commands: `start`, `stop`, `status`, `process`, `names`, `doctor`; stop-time questions; desktop notification |
| `src/leus_notes/recorder.py` | `pactl` default mic + the monitor of every sink (`recording.outputs = "all"`), one `ffmpeg` with `-f pulse` inputs → `me.flac` and the `amix` of all monitors → `them.flac` (mono 16 kHz). Auto-stop: ffmpeg also streams mic+outputs as raw PCM to stdout and `watch_level` counts consecutive seconds below `silence_threshold_db` (RMS). `silencedetect` was dropped: it is per-sample, so room noise peaks never let it fire. Stops ffmpeg with `q` on stdin; `PR_SET_PDEATHSIG` so ffmpeg never outlives us. |
| `src/leus_notes/control.py` | `run/recording.json` (active recording, PID) and `run/stop.json` (what `leus-notes stop` asked for). `stop` writes the request, then sends SIGTERM; Ctrl+C is SIGINT → asks in the recording terminal. |
| `src/leus_notes/transcriber.py` | faster-whisper wrapper. Audio is decoded by the `ffmpeg` binary (faster-whisper's PyAV path breaks with PyAV ≥ 19). Speech regions come from faster-whisper's Silero VAD, merged when < 1 s apart, grouped into ~30 s of speech, and each group is transcribed from a sliced array with `clip_timestamps` and `vad_filter=False` — the built-in `vad_filter` concatenates speech and misplaces words at chunk boundaries (see `/docker/.known-issues/faster-whisper/`). The language is detected per group, restricted to `transcription.languages` (handles English→Croatian switches; avoids Croatian being detected as Serbian/Bosnian). Segments are also split on > 1 s word gaps. |
| `src/leus_notes/diarizer.py` | pyannote pipeline on an in-memory waveform; uses `exclusive_speaker_diarization` when available |
| `src/leus_notes/speakers.py` | Word → speaker assignment (max overlap, nearest turn fallback), renumbering to `1..N` by first appearance, carrying names over after `--redo-speakers` |
| `src/leus_notes/transcript.py` | Display names, merging consecutive lines, markdown/plain rendering |
| `src/leus_notes/notes.py` | `claude -p` call (JSON output, `is_error` check), request and notes header |
| `src/leus_notes/pipeline.py` | `process()`: transcribe → separate speakers → transcript → notes → audio cleanup; each step skipped when its output exists. `Engine` wraps the heavy parts so tests can fake them. |
| `src/leus_notes/sharing.py` | `leus-notes share`: Google login (`InstalledAppFlow.run_local_server`, token refresh), Drive v3 REST through `AuthorizedSession` — find-or-create the `sharing.folder` folder by name, multipart upload of the notes as HTML converted to a Google Doc, `files.update` with new HTML to replace an existing Doc's content. Markdown → HTML with markdown-it-py (`html` off); the notes already carry `owner.name`, so nothing is rewritten at upload. `refresh()` updates only a live Doc; `share()` falls back to creating one. Google libraries are imported lazily so `install.py`/`doctor` stay stdlib-only at import time. |
| `src/leus_notes/meeting.py` | Meeting folder + `meta.json`, folder naming, latest-meeting lookup, `audio.keep_days` sweep (runs before every command) |
| `prompts/notes_system.md` | System prompt for the notes (`{notes_language}`, `{owner}` placeholders — `owner.name` labels the recorder and tells Claude that mentions of that name mean the recorder) |

## Data model

- Speaker ids in `segments.json`: `me`, `1…N`, or `them` (call audio that
  could not be separated). Names live in `meta.json` `names` (`{"1": "Marko"}`)
  and are applied only at render time, so renaming never needs the audio.
- `meta.json` `google_doc_id` / `google_doc_url` link a meeting to its shared
  Doc; `process()` returns whether notes were written, and `run_pipeline` then
  refreshes that Doc.
- `them-words.json` keeps word timings of the call audio so
  `--redo-speakers` only reruns pyannote, not Whisper.
- `--number-of-people` includes the user; pyannote gets `N-1`
  (`PeopleCount.diarization_options`). Exactly 2 → no diarization.

## Dependencies

Pinned to the versions verified on the RTX 4090 setup (`requirements*.txt`);
re-check the CUDA notes below before bumping any of them.

- `faster-whisper` 1.2.1 → CTranslate2 4.8.3, which only dlopens
  `libcublas.so.12` (no cuDNN) → `requirements-gpu.txt` installs
  `nvidia-cublas-cu12` (lands in `nvidia/cublas/lib`).
- `pyannote.audio` 4.x pulls PyTorch from PyPI (CUDA 13 wheels in
  `nvidia/cu13/lib`, cuDNN 9 for CUDA 13 in `nvidia/cudnn/lib`).
- **Never add `nvidia-cudnn-cu12`**: it writes the same files into
  `nvidia/cudnn/lib` and silently replaces torch's cuDNN.
- The speaker model is gated: needs `HF_TOKEN` in `.env` and accepted
  conditions on Hugging Face.

## Tests

```
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```

Unit tests never load models or call Claude (`FakeEngine`, mocked
`subprocess.run`). Real end-to-end checks: `leus-notes doctor --download-models`
and a short real recording.
