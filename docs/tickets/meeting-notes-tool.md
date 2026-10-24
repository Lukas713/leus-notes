# Meeting notes tool (leus-notes)

**Date:** 2026-10-24
**Status:** In progress

## Goal

A personal tool that records an online call on this Linux machine and, when
the call ends, produces written meeting notes — without paying for the Claude
API. Note-writing uses the existing Claude Max subscription (via the logged-in
Claude Code CLI); speech-to-text and speaker separation run locally on this
machine.

## Installation

- One command, `python3 install.py`, sets everything up: checks the system
  (Python, ffmpeg, PipeWire, GPU, Claude login), creates the Python
  environment, installs requirements, downloads the speech models, asks for
  the Hugging Face token (needed once for the speaker-separation model),
  verifies the GPU, creates `config.toml` and links the `leus-notes` command
  into `~/.local/bin`.
- Re-running it is safe. `python3 install.py --uninstall` removes the link.
- Everything is written in Python — installer and command alike.

## How it is used

- `leus-notes start "Discussion about sample" --number-of-people=3` starts
  recording a call happening on this computer (Google Meet, Zoom, Teams — in
  the browser or the desktop app): both my microphone and what the other
  people say through my headset.
- `--number-of-people` counts everyone who speaks during the call, including
  me and people who join late. It can be a single number (`3`) or a range
  (`3-5`); left out, the tool estimates it.
- Stopping:
  - **Ctrl+C** in the recording terminal, or
  - `leus-notes stop` from another terminal (asks the questions there;
    `leus-notes stop --number-of-people=4` skips the question).
  - Optional auto-stop after N minutes of silence (configurable, off by
    default).
- On stop the tool asks how many people spoke (Enter keeps the number given
  at start). A recording of only a few seconds asks whether to discard it
  instead.
- After stopping, automatically:
  1. turn the recording into a text transcript, marking who spoke — **Me**
     or **Speaker 1…N** for the other people;
  2. have Claude write structured notes from that transcript;
  3. show a desktop notification when the notes are ready.
- `leus-notes names` (latest meeting by default) walks through each speaker,
  shows a few of their lines, and asks for a name. The transcript is relabeled
  and Claude rewrites the notes with real names. Giving two speakers the same
  name merges them. Works after the audio is deleted. Non-interactive form:
  `leus-notes names "Speaker 1=Marko" "Speaker 2=Ana"`.
- `leus-notes process [folder]` re-runs whatever is missing; with
  `--redo-speakers --number-of-people=N` it redoes speaker separation while
  the audio still exists.
- `leus-notes status` shows whether a recording is running.

## Languages

- Meetings are in **English or Croatian**.
- Notes are **always written in English**, regardless of the meeting language.

## Output

Each meeting gets its own local folder with:

- `notes.md` — the meeting notes
- `transcript.md` — the full transcript with timestamps and speaker labels
- the transcript as data (so names can be assigned later)

## What the notes contain

- Short summary
- Main discussion points, grouped by topic
- Decisions made
- Action items (who, what, when — when mentioned)
- Open questions / follow-ups

## Configuration (`config.toml`)

- My own label in transcripts (default `Me`)
- How long to keep the raw audio — default: delete as soon as the first notes
  are written; can be N days or forever. If something fails, the audio is
  always kept so the meeting can be reprocessed.
- Auto-stop on silence (minutes, off by default)
- Speech model, meeting languages, Claude model, notes language, meetings
  folder

## Out of scope (for now)

- Live notes during the call
- In-person meetings recorded through a single microphone
- Uploading to Google Drive
- Auto-starting from Google Calendar
- Recognising people by voice across meetings (names are assigned per meeting)

## Constraints

- No Anthropic API key and no API billing — only the Claude subscription.
- Everything (code, models, recordings, notes) stays inside
  `/docker/leusAI/leus-notes/`, except the `~/.local/bin/leus-notes` link.
