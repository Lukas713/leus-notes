from datetime import datetime, timezone
from pathlib import Path

from leus_notes.meeting import Meeting
from leus_notes.speakers import ME, THEM, Utterance
from leus_notes.transcript import (
    Line,
    build_lines,
    display_name,
    format_duration,
    format_timestamp,
    participants,
    render_markdown,
    render_plain,
    spoken_languages,
)


def test_display_names():
    names = {"1": "Marko"}
    assert display_name(ME, names, "Me") == "Me"
    assert display_name(THEM, names, "Me") == "Them"
    assert display_name("1", names, "Me") == "Marko"
    assert display_name("2", names, "Me") == "Speaker 2"


def test_build_lines_merges_close_lines_of_the_same_speaker():
    utterances = [
        Utterance(0.0, 2.0, "1", "Friday is tight."),
        Utterance(3.0, 4.0, "1", "Monday for sure."),
        Utterance(9.0, 10.0, "1", "Later point."),
        Utterance(10.5, 11.0, ME, "Okay."),
    ]
    assert build_lines(utterances, {}, "Me") == [
        Line(0.0, "Speaker 1", "Friday is tight. Monday for sure."),
        Line(9.0, "Speaker 1", "Later point."),
        Line(10.5, "Me", "Okay."),
    ]


def test_same_name_merges_two_speakers():
    utterances = [Utterance(0, 1, "1", "Hello"), Utterance(1.5, 2, "3", "again")]
    assert build_lines(utterances, {"1": "Marko", "3": "Marko"}, "Me") == [Line(0, "Marko", "Hello again")]


def test_formatting():
    assert format_timestamp(3725.9) == "01:02:05"
    assert format_duration(20) == "under 1 min"
    assert format_duration(47 * 60) == "47 min"
    assert format_duration(72 * 60) == "1 h 12 min"


def test_render():
    meeting = Meeting(
        folder=Path("/tmp/x"),
        title="Sample call",
        started_at=datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc),
        duration=600,
        languages={"me": ["hr"], "them": ["en", "hr"]},
    )
    lines = [Line(3, "Me", "Bok."), Line(9, "Speaker 1", "Hi.")]
    assert participants(lines) == ["Me", "Speaker 1"]
    assert spoken_languages(meeting) == "Croatian, English"
    markdown = render_markdown(meeting, lines)
    assert markdown.startswith("# Transcript — Sample call\n\n2026-10-24 14:00 · 10 min · Me, Speaker 1\n\n")
    assert "[00:00:03] **Me:** Bok.\n\n[00:00:09] **Speaker 1:** Hi.\n" in markdown
    assert render_plain(lines) == "[00:00:03] Me: Bok.\n[00:00:09] Speaker 1: Hi."
