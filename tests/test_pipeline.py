import json
from datetime import datetime, timezone

import pytest

from leus_notes.config import Settings
from leus_notes.diarizer import DiarizationError, Turn
from leus_notes.meeting import Meeting
from leus_notes.notes import NotesError
from leus_notes.pipeline import PipelineError, process
from leus_notes.speakers import ME, THEM, load_utterances
from leus_notes.transcriber import ChannelTranscript, Segment, Word

START = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)

MINE = ChannelTranscript(("hr",), 60.0, (Segment(1.0, 2.0, "Možemo li uzorke do petka?"),))
THEIRS = ChannelTranscript(
    ("en",),
    60.0,
    (
        Segment(3.0, 4.0, "Friday is tight.", (Word(3.0, 3.5, " Friday"), Word(3.5, 4.0, " is tight."))),
        Segment(5.0, 6.0, "I'll check stock.", (Word(5.0, 6.0, " I'll check stock."),)),
    ),
)


class FakeEngine:
    def __init__(self, turns=None, diarization_error=None, notes_error=None):
        self.turns = turns or [Turn(2.5, 4.5, "SPEAKER_01"), Turn(4.5, 7.0, "SPEAKER_00")]
        self.diarization_error = diarization_error
        self.notes_error = notes_error
        self.calls = []

    def prepare_transcriber(self):
        pass

    def transcribe(self, audio):
        self.calls.append(("transcribe", audio.name))
        return THEIRS if audio.name == "them.flac" else MINE

    def release_transcriber(self):
        self.calls.append(("release",))

    def diarize(self, audio, people):
        self.calls.append(("diarize", str(people)))
        if self.diarization_error:
            raise self.diarization_error
        return self.turns

    def write_notes(self, request):
        self.calls.append(("notes", request))
        if self.notes_error:
            raise self.notes_error
        return "## Summary\nSamples ship Monday."


def make_meeting(tmp_path, people="3", audio=True):
    meeting = Meeting.create(tmp_path / "meetings", "Sample call", START, people, {})
    if audio:
        meeting.me_audio.write_bytes(b"me")
        meeting.them_audio.write_bytes(b"them")
    return meeting


def settings(tmp_path, keep_audio_days=0):
    root = tmp_path / "root"
    (root / "prompts").mkdir(parents=True, exist_ok=True)
    (root / "prompts" / "notes_system.md").write_text("Notes in {notes_language}. {me_label} recorded.")
    return Settings(root=root, meetings_dir=tmp_path / "meetings", keep_audio_days=keep_audio_days)


def quiet(message):
    pass


def test_full_run_with_speaker_separation(tmp_path):
    meeting = make_meeting(tmp_path)
    engine = FakeEngine()
    process(meeting, settings(tmp_path), engine, log=quiet)
    assert [call[0] for call in engine.calls] == ["transcribe", "transcribe", "release", "diarize", "notes"]
    assert [(u.speaker, u.text) for u in load_utterances(meeting.segments_path)] == [
        (ME, "Možemo li uzorke do petka?"),
        ("1", "Friday is tight."),
        ("2", "I'll check stock."),
    ]
    assert "[00:00:03] **Speaker 1:** Friday is tight." in meeting.transcript_path.read_text()
    assert meeting.notes_path.read_text().startswith("# Sample call\n")
    assert json.loads(meeting.words_path.read_text())["languages"] == ["en"]
    assert meeting.languages == {"me": ["hr"], "them": ["en"]}
    assert not meeting.has_audio()


def test_two_people_skip_speaker_separation(tmp_path):
    meeting = make_meeting(tmp_path, people="2")
    engine = FakeEngine()
    process(meeting, settings(tmp_path), engine, log=quiet)
    assert "diarize" not in [call[0] for call in engine.calls]
    assert {u.speaker for u in load_utterances(meeting.segments_path)} == {ME, "1"}


def test_failed_speaker_separation_labels_them_and_keeps_audio(tmp_path):
    meeting = make_meeting(tmp_path)
    process(meeting, settings(tmp_path), FakeEngine(diarization_error=DiarizationError("no token")), log=quiet)
    assert {u.speaker for u in load_utterances(meeting.segments_path)} == {ME, THEM}
    assert meeting.keep_audio_reason == "speaker separation failed: no token"
    assert meeting.notes_path.exists()
    assert meeting.has_audio()


def test_notes_failure_keeps_audio_and_retry_only_redoes_notes(tmp_path):
    meeting = make_meeting(tmp_path)
    with pytest.raises(NotesError):
        process(meeting, settings(tmp_path), FakeEngine(notes_error=NotesError("limit reached")), log=quiet)
    assert meeting.segments_path.exists()
    assert not meeting.notes_path.exists()
    assert meeting.has_audio()
    retry = FakeEngine()
    process(meeting, settings(tmp_path), retry, log=quiet)
    assert [call[0] for call in retry.calls] == ["notes"]
    assert not meeting.has_audio()


def test_keep_days_keeps_audio_after_notes(tmp_path):
    meeting = make_meeting(tmp_path)
    process(meeting, settings(tmp_path, keep_audio_days=7), FakeEngine(), log=quiet)
    assert meeting.has_audio()


def test_redo_speakers_reuses_transcript_and_carries_names(tmp_path):
    meeting = make_meeting(tmp_path)
    config = settings(tmp_path, keep_audio_days=7)
    process(meeting, config, FakeEngine(), log=quiet)
    meeting.names = {"1": "Marko", "2": "Ana"}
    meeting.people = "4"
    meeting.save()
    split = FakeEngine(turns=[Turn(2.5, 3.5, "B"), Turn(3.5, 4.5, "C"), Turn(4.5, 7.0, "A")])
    process(meeting, config, split, redo_speakers=True, log=quiet)
    assert [call[0] for call in split.calls] == ["diarize", "notes"]
    assert split.calls[0] == ("diarize", "4")
    assert [(u.speaker, u.text) for u in load_utterances(meeting.segments_path)] == [
        (ME, "Možemo li uzorke do petka?"),
        ("1", "Friday"),
        ("2", "is tight."),
        ("3", "I'll check stock."),
    ]
    assert meeting.names == {"1": "Marko", "2": "Marko", "3": "Ana"}


def test_redo_speakers_without_audio_explains_why(tmp_path):
    meeting = make_meeting(tmp_path)
    config = settings(tmp_path)
    process(meeting, config, FakeEngine(), log=quiet)
    with pytest.raises(PipelineError, match="keep_days"):
        process(meeting, config, FakeEngine(), redo_speakers=True, log=quiet)


def test_names_rewrite_notes_without_audio(tmp_path):
    meeting = make_meeting(tmp_path)
    config = settings(tmp_path)
    process(meeting, config, FakeEngine(), log=quiet)
    meeting.names = {"1": "Marko"}
    engine = FakeEngine()
    process(meeting, config, engine, rewrite_notes=True, log=quiet)
    assert [call[0] for call in engine.calls] == ["notes"]
    assert "Marko: Friday is tight." in engine.calls[0][1]
    assert "**Marko:** Friday is tight." in meeting.transcript_path.read_text()


def test_no_speech_keeps_audio_and_can_be_retried(tmp_path):
    meeting = make_meeting(tmp_path)
    silent = FakeEngine()
    silent.transcribe = lambda audio: ChannelTranscript((), 60.0, ())
    with pytest.raises(PipelineError, match="No speech"):
        process(meeting, settings(tmp_path), silent, log=quiet)
    assert meeting.has_audio()
    assert meeting.keep_audio_reason == "no speech was detected"
    assert not meeting.segments_path.exists()
    retry = FakeEngine()
    process(meeting, settings(tmp_path), retry, log=quiet)
    assert [call[0] for call in retry.calls][:2] == ["transcribe", "transcribe"]
    assert meeting.notes_path.exists()
    assert meeting.keep_audio_reason is None


def test_missing_audio_before_transcription(tmp_path):
    meeting = make_meeting(tmp_path, audio=False)
    with pytest.raises(PipelineError, match="no longer available"):
        process(meeting, settings(tmp_path), FakeEngine(), log=quiet)
