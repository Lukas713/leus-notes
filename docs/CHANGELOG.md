# Changelog

- 2026-10-24 — Initial version: record calls (mic + call audio), local Whisper transcription, pyannote speaker separation, English notes via `claude -p` on the Claude subscription, `names`/`process`/`status`/`doctor` commands, Python installer.
- 2026-10-27 — `leus-notes share`: upload a meeting's notes as a formatted Google Doc into one team folder in Google Drive (opt-in per meeting, notes only, "Me" shown as `sharing.my_name`); the same Doc is updated when notes are rewritten; Google login check in `doctor`.
- 2026-10-27 — `owner.name` (default "Lukas") replaces `recording.me_label` and `sharing.my_name`: your name instead of "Me" in transcripts, notes and shared Docs; Claude is told that mentions of that name mean the recorder.
