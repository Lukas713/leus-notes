from __future__ import annotations

import json
import sys
import time
from collections.abc import Callable

from .config import Settings
from .diarizer import DiarizationError, Turn, diarize, load_pipeline
from .meeting import Meeting, write_json
from .notes import ask_claude, notes_request, render_notes, system_prompt
from .people import PeopleCount
from .speakers import (
    ME,
    THEM,
    Utterance,
    carry_names,
    load_utterances,
    renumber,
    save_utterances,
    single_speaker,
    split_by_turns,
)
from .transcriber import ChannelTranscript, Transcriber
from .transcript import build_lines, render_markdown

Log = Callable[[str], None]
NO_SPEECH = (
    "No speech was detected on your microphone or in the call audio. "
    "Check the recorded devices with `leus-notes doctor`; the audio is kept."
)


class PipelineError(Exception):
    pass


def log_to_stdout(message: str) -> None:
    print(message, flush=True)


class Engine:
    def __init__(self, settings: Settings, log: Log = log_to_stdout):
        self.settings = settings
        self.log = log
        self.transcriber: Transcriber | None = None

    def prepare_transcriber(self) -> None:
        if self.transcriber is None:
            self.log(f"Loading speech model {self.settings.whisper_model}…")
            self.transcriber = Transcriber(
                self.settings.whisper_model,
                self.settings.device,
                self.settings.models_dir / "whisper",
                self.settings.language,
                self.settings.languages,
            )

    def transcribe(self, audio) -> ChannelTranscript:
        self.prepare_transcriber()
        return self.transcriber.transcribe(audio, progress=show_progress)

    def release_transcriber(self) -> None:
        if self.transcriber is not None:
            self.transcriber.close()
            self.transcriber = None

    def diarize(self, audio, people: PeopleCount) -> list[Turn]:
        pipeline = load_pipeline(self.settings.diarization_model, self.settings.hf_token)
        return diarize(pipeline, audio, people.diarization_options())

    def write_notes(self, request: str) -> str:
        settings = self.settings
        return ask_claude(
            request,
            model=settings.claude_model,
            prompt=system_prompt(settings.prompts_dir, settings.notes_language, settings.me_label),
            cwd=settings.root,
            timeout=settings.claude_timeout_seconds,
        )


def show_progress(fraction: float) -> None:
    if sys.stdout.isatty():
        print(f"\r  {fraction:4.0%}", end="", flush=True)


def finish_progress() -> None:
    if sys.stdout.isatty():
        print("\r  100%", flush=True)


def process(
    meeting: Meeting,
    settings: Settings,
    engine: Engine,
    *,
    redo_speakers: bool = False,
    rewrite_notes: bool = False,
    log: Log = log_to_stdout,
) -> None:
    people = PeopleCount.parse(meeting.people)
    if redo_speakers:
        require_audio(meeting, settings)
        separate_speakers_again(meeting, engine, people, log)
        rewrite_notes = True
    elif not meeting.segments_path.exists():
        require_audio(meeting, settings)
        transcribe(meeting, engine, people, log)
    utterances = load_utterances(meeting.segments_path)
    if not utterances:
        raise PipelineError(NO_SPEECH)
    lines = build_lines(utterances, meeting.names, settings.me_label)
    meeting.transcript_path.write_text(render_markdown(meeting, lines))
    if rewrite_notes or not meeting.notes_path.exists():
        log(f"Writing notes with Claude ({settings.claude_model})…")
        started = time.monotonic()
        body = engine.write_notes(notes_request(meeting, lines, people))
        meeting.notes_path.write_text(render_notes(meeting, lines, body))
        log(f"  done in {time.monotonic() - started:.0f} s")
    if settings.keep_audio_days == 0 and meeting.has_audio() and not meeting.keep_audio_reason:
        meeting.delete_audio()
        log("Audio deleted (audio.keep_days = 0).")


def require_audio(meeting: Meeting, settings: Settings) -> None:
    if meeting.has_complete_audio():
        return
    hint = " Set audio.keep_days in config.toml to keep audio for re-runs." if settings.keep_audio_days == 0 else ""
    raise PipelineError(f"The audio for this meeting is no longer available in {meeting.folder}.{hint}")


def timed(log: Log, label: str, action: Callable[[], ChannelTranscript]) -> ChannelTranscript:
    log(label)
    started = time.monotonic()
    result = action()
    finish_progress()
    languages = ", ".join(result.languages) or "none"
    log(f"  done in {time.monotonic() - started:.0f} s ({len(result.segments)} segments, language: {languages})")
    return result


def transcribe(meeting: Meeting, engine: Engine, people: PeopleCount, log: Log) -> None:
    engine.prepare_transcriber()
    me = timed(log, "Transcribing your microphone…", lambda: engine.transcribe(meeting.me_audio))
    them = timed(log, "Transcribing the call audio…", lambda: engine.transcribe(meeting.them_audio))
    engine.release_transcriber()
    if not me.segments and not them.segments:
        meeting.keep_audio_reason = "no speech was detected"
        meeting.save()
        raise PipelineError(NO_SPEECH)
    write_json(meeting.words_path, them.to_dict())
    them_utterances = assign_speakers(meeting, engine, people, them, log)
    meeting.languages = {
        channel: list(transcript.languages) for channel, transcript in (("me", me), ("them", them)) if transcript.segments
    }
    meeting.duration = max(me.duration, them.duration)
    save_utterances(meeting.segments_path, renumber(single_speaker(me.segments, ME) + them_utterances))
    meeting.save()


def separate_speakers_again(meeting: Meeting, engine: Engine, people: PeopleCount, log: Log) -> None:
    if not meeting.words_path.exists() or not meeting.segments_path.exists():
        transcribe(meeting, engine, people, log)
        return
    them = ChannelTranscript.from_dict(json.loads(meeting.words_path.read_text()))
    old = load_utterances(meeting.segments_path)
    mine = [utterance for utterance in old if utterance.speaker == ME]
    new = renumber(mine + assign_speakers(meeting, engine, people, them, log))
    meeting.names = carry_names(old, new, meeting.names)
    save_utterances(meeting.segments_path, new)
    meeting.save()


def assign_speakers(
    meeting: Meeting,
    engine: Engine,
    people: PeopleCount,
    them: ChannelTranscript,
    log: Log,
) -> list[Utterance]:
    meeting.keep_audio_reason = None
    if not them.segments:
        return []
    if not people.needs_speaker_separation():
        return single_speaker(them.segments, "1")
    log(f"Separating speakers (people: {people})…")
    started = time.monotonic()
    try:
        turns = engine.diarize(meeting.them_audio, people)
    except DiarizationError as error:
        log(f"  speaker separation skipped: {error}")
        meeting.keep_audio_reason = f"speaker separation failed: {error}"
        return single_speaker(them.segments, THEM)
    if not turns:
        log("  no separate voices found; the other side is labeled 'Them'")
        meeting.keep_audio_reason = "speaker separation found no voices"
        return single_speaker(them.segments, THEM)
    log(f"  done in {time.monotonic() - started:.0f} s ({len({turn.speaker for turn in turns})} voices)")
    return split_by_turns(them.segments, turns)
