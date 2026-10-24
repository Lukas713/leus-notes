import stat
from datetime import datetime, timedelta, timezone

import pytest

from leus_notes.meeting import Meeting, MeetingNotFound, find_meeting, slugify, sweep_audio

START = datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    ("title", "slug"),
    [
        ("Discussion about sample", "discussion-about-sample"),
        ("Čišćenje: đak & Žaba!", "ciscenje-dak-zaba"),
        ("../../etc/passwd", "etc-passwd"),
        ("", "meeting"),
        ("???", "meeting"),
    ],
)
def test_slugify(title, slug):
    assert slugify(title) == slug


def make_meeting(meetings_dir, title="Client call", started_at=START, notes=False, audio=False):
    meeting = Meeting.create(meetings_dir, title, started_at, "3", {"mic": "m", "call": "c"})
    meeting.stopped_at = started_at + timedelta(minutes=30)
    meeting.save()
    if notes:
        meeting.notes_path.write_text("notes")
    if audio:
        meeting.me_audio.write_bytes(b"x")
        meeting.them_audio.write_bytes(b"x")
    return meeting


def test_create_names_folder_and_avoids_collisions(tmp_path):
    first = make_meeting(tmp_path)
    second = make_meeting(tmp_path)
    assert first.folder.name == "2026-10-24_1400_client-call"
    assert second.folder.name == "2026-10-24_1400_client-call-2"


def test_meeting_folder_is_private(tmp_path):
    meeting = make_meeting(tmp_path / "nested" / "meetings")
    assert stat.S_IMODE(meeting.folder.stat().st_mode) == 0o700


def test_save_and_load_round_trip(tmp_path):
    meeting = make_meeting(tmp_path)
    meeting.names = {"1": "Marko"}
    meeting.languages = {"me": ["hr"], "them": ["en", "hr"]}
    meeting.keep_audio_reason = "speaker separation failed"
    meeting.save()
    loaded = Meeting.load(meeting.folder)
    assert loaded == meeting


def test_find_latest_and_by_name(tmp_path):
    older = make_meeting(tmp_path, "Old", START)
    newer = make_meeting(tmp_path, "New", START + timedelta(days=1))
    assert find_meeting(tmp_path).folder == newer.folder
    assert find_meeting(tmp_path, older.folder.name).folder == older.folder
    assert find_meeting(tmp_path, str(older.folder)).folder == older.folder


def test_find_latest_transcribed(tmp_path):
    transcribed = make_meeting(tmp_path, "Done", START)
    transcribed.segments_path.write_text('{"utterances": []}')
    make_meeting(tmp_path, "Recording", START + timedelta(hours=1))
    assert find_meeting(tmp_path, transcribed=True).folder == transcribed.folder


def test_find_latest_skips_the_running_recording(tmp_path):
    finished = make_meeting(tmp_path, "Finished", START)
    running = make_meeting(tmp_path, "Running", START + timedelta(hours=1))
    assert find_meeting(tmp_path, skip=running.folder.resolve()).folder == finished.folder


def test_find_missing(tmp_path):
    with pytest.raises(MeetingNotFound):
        find_meeting(tmp_path)
    with pytest.raises(MeetingNotFound):
        find_meeting(tmp_path, "nope")


def test_sweep_deletes_audio_only_after_notes_and_age(tmp_path):
    done = make_meeting(tmp_path, "Done", notes=True, audio=True)
    unprocessed = make_meeting(tmp_path, "Unprocessed", audio=True)
    later = START + timedelta(days=3)
    assert sweep_audio(tmp_path, keep_days=7, moment=later) == []
    swept = sweep_audio(tmp_path, keep_days=2, moment=later)
    assert [meeting.folder for meeting in swept] == [done.folder]
    assert not done.has_audio()
    assert unprocessed.has_audio()


def test_sweep_keeps_audio_forever_or_when_flagged(tmp_path):
    kept = make_meeting(tmp_path, "Kept", notes=True, audio=True)
    kept.keep_audio_reason = "speaker separation failed"
    kept.save()
    other = make_meeting(tmp_path, "Other", notes=True, audio=True)
    later = START + timedelta(days=30)
    assert sweep_audio(tmp_path, keep_days=-1, moment=later) == []
    assert [meeting.folder for meeting in sweep_audio(tmp_path, keep_days=0, moment=later)] == [other.folder]
    assert kept.has_audio()
