# leus-notes

Records a call on this Linux machine and turns it into English meeting notes.
Speech-to-text and speaker separation run locally on the GPU; the notes are
written by Claude through the logged-in **Claude Code CLI**, so they use your
Claude subscription — no API key, no API billing. When you want colleagues
to read them, one command turns a meeting's notes into a Google Doc.

```
leus-notes start "Discussion about sample" --number-of-people=3
… call …
Ctrl+C
Number of people who spoke? [3]:
→ meetings/2026-10-24_1400_discussion-about-sample/notes.md
```

## How it works

1. **Record** — `ffmpeg` records two separate tracks from PipeWire: your
   default microphone (`me.flac`) and everything played on your output
   devices, i.e. what you hear (`them.flac`). All outputs are recorded and
   mixed by default, so the call is captured even when the call app plays on
   a headset that isn't the system default. Keeping the two tracks apart is
   what labels every line with your name (`owner.name`, default **Lukas**)
   or someone else.
2. **Transcribe** — [faster-whisper](https://github.com/SYSTRAN/faster-whisper)
   (`large-v3`) transcribes each track on the GPU. Speech regions are found
   first and transcribed one by one, so silence is skipped and timestamps stay
   exact. The language is detected for every ~30 s of speech among the
   configured languages (English and Croatian by default), so a call that
   switches from English to Croatian is transcribed correctly in both.
3. **Separate speakers** — for calls with 3 or more people,
   [pyannote](https://github.com/pyannote/pyannote-audio)
   (`speaker-diarization-community-1`) splits the call audio into
   Speaker 1 … N. Knowing the number of people makes this much more reliable.
   With exactly 2 people this step is skipped: the other side is Speaker 1.
4. **Write notes** — the tool first checks that `claude` is logged in with a
   claude.ai subscription (and refuses otherwise), then sends the transcript
   to `claude -p` in safe mode (no tools, no CLAUDE.md, no hooks, no MCP, no
   API-key or Bedrock/Vertex variables). Claude returns notes with Summary,
   Discussion, Decisions, Action items and Open questions — always in English.
5. **Finish** — `notes.md` and `transcript.md` stay in the meeting folder, a
   desktop notification pops up, and the audio is deleted (configurable).
6. **Share (optional)** — `leus-notes share` uploads the notes as a formatted
   Google Doc into one Drive folder you share with your team. See
   [Sharing notes as Google Docs](#sharing-notes-as-google-docs).

## Requirements

| What | Needed for | Notes |
|---|---|---|
| Linux with PipeWire (`pactl`) | recording | the call must play on this computer |
| `ffmpeg` | recording, decoding | `sudo apt install ffmpeg` |
| Python ≥ 3.11 | everything | the installer creates its own `.venv` |
| Claude Code, logged in with a claude.ai subscription | notes | `claude` → `/login`; API-key logins are refused |
| NVIDIA GPU with a current driver | fast transcription | optional — without it Whisper runs on the CPU, much slower |
| Hugging Face account + read token | Speaker 1 … N in calls with 3+ people | optional, free — see [Hugging Face token](#hugging-face-token-for-speaker-1--n) |
| Google account + your own Google Cloud OAuth client | `leus-notes share` | optional, free — see [One-time setup](#one-time-setup-about-10-minutes) |
| `notify-send` (`libnotify-bin`) | desktop notification | optional |
| About 10 GB of disk | `.venv` (PyTorch, CUDA libraries) and models | everything stays in this folder |

## Installation

```
python3 install.py
```

The installer:

- checks Python ≥ 3.11, `ffmpeg`, `pactl`, `notify-send`, the GPU, and that
  `claude` is logged in with a claude.ai subscription;
- creates `.venv` and installs the packages (several GB: PyTorch and CUDA
  libraries);
- creates `config.toml` from `config.example.toml`;
- asks for a Hugging Face token (see below) and stores it in `.env`;
- downloads and tests the speech and speaker models (`models/`);
- links `~/.local/bin/leus-notes` to this folder.

**Updating:** after pulling a new version, run `python3 install.py` again so
new packages get installed (e.g. the Google libraries for `share`). Your
`config.toml`, `.env`, `google/` and `meetings/` are kept; compare your
`config.toml` with `config.example.toml` for new or renamed settings — an
unknown setting stops the tool with a message naming it.

Re-running it is safe. Options: `--skip-models`, `--force` (replace an
existing `~/.local/bin/leus-notes`), `--uninstall` (remove the link),
`--uninstall --purge` (also delete `.venv`, `models/` and caches — never
`meetings/`).

### Hugging Face token (for Speaker 1 … N)

The speaker-separation model is free but gated:

1. create an account at <https://huggingface.co/join>;
2. accept the conditions at
   <https://huggingface.co/pyannote/speaker-diarization-community-1>;
3. create a **read** token at <https://huggingface.co/settings/tokens>;
4. run `python3 install.py` again and paste it (or put `HF_TOKEN=hf_…` in
   `.env`).

Without a token everything still works; calls with 3+ people simply label
the whole other side "Them".

## Usage

| Command | What it does |
|---|---|
| `leus-notes start "Title" --number-of-people=N` | Start recording. `N` counts everyone who speaks, including you and late joiners: `3`, a range `3-5`, or leave it out to let the tool estimate. |
| Ctrl+C in the recording terminal | Stop. Asks how many people spoke (Enter keeps your number) and starts processing. A recording shorter than `min_duration_seconds` asks whether to discard it. |
| `leus-notes stop [--number-of-people=N]` | Stop from another terminal; asks the same questions there unless `--number-of-people` is given. |
| `leus-notes status` | Is a recording running? State of the latest meeting. |
| `leus-notes names [meeting]` | Name the speakers of a meeting (latest by default). Shows a few lines per speaker, asks for a name, relabels the transcript and has Claude rewrite the notes. Giving two speakers the same name merges them. |
| `leus-notes names [meeting] "Speaker 1=Marko" "2=Ana"` | Same, without questions. `"Speaker 1="` removes a name. |
| `leus-notes process [meeting]` | Finish whatever is missing (e.g. after a failure). |
| `leus-notes process [meeting] --redo-speakers --number-of-people=N` | Separate speakers again with a corrected count while the audio still exists. Names already assigned carry over where the voices still match. |
| `leus-notes process [meeting] --notes` | Rewrite the notes (e.g. after editing `segments.json` or the prompt). |
| `leus-notes share [meeting]` | Upload the notes as a Google Doc into your team folder in Google Drive and print the link (latest meeting by default). Running it again updates the same Doc. See [Sharing notes as Google Docs](#sharing-notes-as-google-docs). |
| `leus-notes doctor [--download-models]` | Check devices, Claude login, GPU, models, the Hugging Face token and the Google login. |

`[meeting]` is a folder name inside `meetings/` or a path.

Tips:

- When unsure about the number of people, guess **high** or give a range.
  Too high splits one person into two speakers — fix it by giving both the
  same name. Too low merges two people, which can't be undone once the audio
  is gone.
- Use a headset. With speakers your microphone also picks up the other side
  and their words appear twice.
- Your microphone is the PipeWire default at the moment you run `start`;
  switching microphones mid-call isn't followed. Output devices are all
  recorded, but one connected after `start` (e.g. Bluetooth) isn't.
- With `recording.outputs = "all"`, anything else playing (music, videos) is
  recorded into the call track too. Pause it during calls, or switch to
  `"default"` if your call app always plays on the system default output.
- Closing the recording terminal stops the recording without processing it;
  run `leus-notes process` afterwards.

## Sharing notes as Google Docs

Nothing is shared automatically. When you want colleagues to read a meeting's
notes, run `leus-notes share [meeting]`: the notes become a formatted Google
Doc (headings, lists, the action-items table) in one Drive folder, and the
command prints its link. Only the notes are uploaded — never the transcript or
the audio. You appear in the Doc under your name (`owner.name`), as in your
local notes.

Once a meeting is shared, its Doc follows the notes: `leus-notes names` and
`leus-notes process --notes` update the **same** Doc, so a link you already
sent keeps working. If you deleted the Doc in Drive, it is not recreated until
you run `share` again.

### One-time setup (about 10 minutes)

The tool needs its own permission to create files in your Drive. It only ever
sees the files and the folder it created itself, not the rest of your Drive.

1. Open <https://console.cloud.google.com/projectcreate> while logged in with
   the Google account that should own the Docs, name the project `leus-notes`
   and create it.
2. With that project selected, open
   <https://console.cloud.google.com/apis/library/drive.googleapis.com> and
   click **Enable**.
3. Open <https://console.cloud.google.com/auth/overview> → **Get started**:
   app name `leus-notes`, your email as support and contact email, audience
   **External**, accept the policy, **Create**.
4. Open <https://console.cloud.google.com/auth/audience> → **Publish app** →
   confirm, so the status reads **In production**. While it says *Testing*,
   Google ends the login after 7 days.
5. Open <https://console.cloud.google.com/auth/clients> → **Create client** →
   application type **Desktop app**, name `leus-notes` → **Create** →
   **Download JSON**.
6. Save the downloaded file as `google/client_secret.json` in this folder.
7. Run `leus-notes share`. The browser opens; choose your account. If Google
   says *"Google hasn't verified this app"*, that's your own app from step 3:
   **Advanced** → **Go to leus-notes**. Allow access to *the specific Google
   Drive files you use with this app*.
8. The first share creates the Drive folder **Meeting notes** and prints its
   link. Open it and **Share** it with your team once — every Doc the tool puts
   in it is visible to them from then on.

The login is stored in `google/token.json` and renews itself. `leus-notes
doctor` shows whether sharing is set up.

Good to know:

- Let the tool create the folder. A folder you create by hand is invisible to
  it, so it would make its own one next to yours.
- Don't rename the folder in Drive (moving it is fine): the tool finds it by
  name and would create a new one. To use another folder, change
  `sharing.folder` in `config.toml`.
- Notes written before `owner.name` existed still say "Me". Run
  `leus-notes process <meeting> --notes` to rewrite them with your name; a
  shared meeting's Doc is updated too.
- The Doc of a meeting shared before setup by other means (e.g. by hand) is
  not linked to the meeting; `share` creates a new one.

## Meeting folder

```
meetings/2026-10-24_1400_discussion-about-sample/
├── notes.md          meeting notes (English)
├── transcript.md     timestamped transcript with speaker labels
├── segments.json     the transcript as data — the source for transcript.md
├── them-words.json   word timings of the call audio (for --redo-speakers)
├── meta.json         title, times, number of people, names, languages, Google Doc link
├── me.flac           your microphone   ┐ deleted after the first notes
└── them.flac         the call audio    ┘ (audio.keep_days)
```

To correct a line that landed on the wrong speaker, change its `speaker` in
`segments.json` and run `leus-notes process <meeting> --notes`.
`transcript.md` is regenerated from `segments.json`, so edits made directly
in `transcript.md` are overwritten.

## Configuration (`config.toml`)

| Setting | Default | Meaning |
|---|---|---|
| `owner.name` | `"Lukas"` | Your name. Used instead of "Me" in transcripts, notes and shared Docs; Claude is told that whoever mentions this name means you |
| `recording.outputs` | `"all"` | `all` = record every output device (safest), `default` = only the system default output |
| `recording.min_duration_seconds` | `10` | Shorter recordings ask whether to discard them |
| `recording.auto_stop_silence_minutes` | `0` | Stop automatically after this many minutes of silence on the mic and all outputs; `0` = off |
| `recording.silence_threshold_db` | `-35` | Average loudness per second (dBFS) below which a second counts as silent. Your mic's room noise must be below it — check with `ffmpeg -f pulse -i "$(pactl get-default-source)" -t 3 -af volumedetect -f null -` |
| `audio.keep_days` | `0` | `0` = delete audio right after the first notes, `N` = keep for N days, `-1` = keep forever. Audio is always kept when something failed. |
| `transcription.model` | `"large-v3"` | faster-whisper model |
| `transcription.device` | `"auto"` | `auto`, `cuda` or `cpu` |
| `transcription.language` | `"auto"` | Force a language (`"hr"`, `"en"`) instead of detecting it |
| `transcription.languages` | `["en", "hr"]` | Languages to choose from when detecting |
| `speakers.model` | `"pyannote/speaker-diarization-community-1"` | Speaker-separation model |
| `notes.claude_model` | `"opus"` | Model passed to `claude --model` |
| `notes.language` | `"English"` | Language of the notes |
| `notes.timeout_seconds` | `600` | How long to wait for Claude |
| `paths.meetings_dir` | `"meetings"` | Where meeting folders go (relative to this folder) |
| `sharing.folder` | `"Meeting notes"` | Drive folder for shared Docs; the tool creates it on the first `share` |

The notes prompt lives in `prompts/notes_system.md`.

## Privacy

Audio, transcripts and models stay in this folder. Only the transcript text
is sent to Claude (with your subscription, like any Claude Code session).
A meeting's notes go to Google Drive only when you run `leus-notes share` for
that meeting. `meetings/`, `google/`, `.env`, `config.toml`, `models/` and
`.venv/` are git-ignored.

## Development

```
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest
```
