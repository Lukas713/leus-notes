# leus-notes — feature overview

## Purpose

Turn an online call held on this machine into English meeting notes without
the Claude API: transcription and speaker separation run locally, the notes
are written by Claude via the user's Claude subscription (`claude -p`).

## Flow

```
leus-notes start "Title" --number-of-people=N
        │  pactl → default mic + monitors of all outputs
        ▼
ffmpeg ── me.flac (mic) ──────────────────────┐
       └─ them.flac (all outputs mixed) ────┐ │
                                            │ │   Ctrl+C / leus-notes stop / silence auto-stop
                                            ▼ ▼   → "Number of people who spoke? [N]"
ffmpeg decode → Silero VAD regions → faster-whisper large-v3 per region
        (GPU, word timings, language from [en, hr])
        │  me → owner.name      them → words with timings
        ▼
pyannote community-1 on them.flac (N-1 voices; skipped when N = 2)
        │  words → Speaker 1…N by overlap, numbered by first appearance
        ▼
segments.json → transcript.md
        ▼
claude -p --safe-mode --tools "" (subscription) → notes.md
        ▼
delete audio (audio.keep_days = 0) · notify-send "Meeting notes ready"
```

## Sharing (Google Docs)

```
leus-notes share [meeting]
        │  google/client_secret.json → browser login once → google/token.json
        ▼
notes.md (already uses owner.name) → markdown-it → HTML
        ▼
Drive (scope drive.file): folder "Meeting notes" (found by name or created)
        │  new meeting → upload HTML as Google Doc into the folder
        │  shared before → replace the content of the same Doc
        ▼
meta.json google_doc_id / google_doc_url · link printed

leus-notes names / process --notes on a shared meeting
        → same Doc updated (no login prompt, never recreated)
```

## Decisions

| Topic | Decision |
|---|---|
| Notes engine | `claude -p` with the logged-in subscription; `--safe-mode` keeps OAuth but disables CLAUDE.md, hooks, MCP, skills; API-key variables stripped |
| Who is the recorder | Separate mic track — always exact; labeled with `owner.name` (default "Lukas"), and Claude is told mentions of that name are the recorder |
| Call audio | Monitors of all output devices mixed (`recording.outputs = "all"`), so a call playing on a non-default headset isn't lost |
| Auto-stop | Per-second RMS of mic + outputs below `silence_threshold_db` (-35) for N minutes; off by default |
| Other speakers | pyannote with the number of people given at start or stop; `Speaker N` until named with `leus-notes names` |
| Late joiners | Count everyone who spoke at any point; correct the number when stopping |
| Wrong count | Too high → merge by giving two speakers the same name; too low → `--redo-speakers` while audio exists |
| Notes language | Always English (configurable) |
| Audio | Deleted after the first notes by default; `audio.keep_days` N / -1; always kept on failure |
| Installation | `python3 install.py` (stdlib only); `leus-notes` launcher is Python too |
| Storage | Everything inside the project folder, except the `~/.local/bin/leus-notes` link |
| Sharing | Opt-in per meeting with `leus-notes share`; notes only; one Drive folder the user shares with the team once |
| Google account | Personal Gmail, own OAuth client (Desktop app), consent screen published "In production" to avoid the 7-day token expiry of "Testing" |
| Google access | `drive.file` only — the tool sees just its own folder and Docs |
| Doc updates | Rewritten notes replace the content of the same Doc (same link); a deleted/trashed Doc is only recreated by an explicit `share` |
| Recorder in shared Docs | Same `owner.name` as in the local notes — no rewriting at upload |

## Limitations

- All other participants share one audio track; separation quality drops with
  overlapping speech, very short interjections and similar voices.
- The microphone is fixed at `start`; output devices connected later aren't recorded.
- Other audio playing during the call (music, videos) ends up in the call track.
- With speakers instead of a headset, the mic picks up the other side.
- Closing the recording terminal stops without processing
  (`leus-notes process` afterwards).
- The shared-Docs folder is found by name: renaming it in Drive makes the tool
  create a new one; a folder made by hand is invisible to the tool.
- Rewriting a shared Doc replaces its whole content; comments colleagues left
  may lose their anchor text.
