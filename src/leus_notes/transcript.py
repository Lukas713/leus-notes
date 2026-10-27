from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from .meeting import Meeting
from .speakers import ME, THEM, Utterance

MERGE_GAP_SECONDS = 2.0
LANGUAGE_NAMES = {"en": "English", "hr": "Croatian", "de": "German", "sr": "Serbian", "bs": "Bosnian", "sl": "Slovenian"}


@dataclass(frozen=True)
class Line:
    start: float
    speaker: str
    text: str


def display_name(speaker: str, names: dict[str, str], owner_name: str) -> str:
    if speaker == ME:
        return owner_name
    if speaker == THEM:
        return "Them"
    return names.get(speaker) or f"Speaker {speaker}"


def build_lines(utterances: Iterable[Utterance], names: dict[str, str], owner_name: str) -> list[Line]:
    lines: list[Line] = []
    previous_end = None
    for utterance in sorted(utterances, key=lambda utterance: utterance.start):
        name = display_name(utterance.speaker, names, owner_name)
        if lines and lines[-1].speaker == name and utterance.start - previous_end <= MERGE_GAP_SECONDS:
            lines[-1] = Line(lines[-1].start, name, f"{lines[-1].text} {utterance.text}")
        else:
            lines.append(Line(utterance.start, name, utterance.text))
        previous_end = utterance.end
    return lines


def participants(lines: Iterable[Line]) -> list[str]:
    return list(dict.fromkeys(line.speaker for line in lines))


def format_timestamp(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 3600:02d}:{total % 3600 // 60:02d}:{total % 60:02d}"


def format_duration(seconds: float) -> str:
    minutes = round(seconds / 60)
    if minutes < 1:
        return "under 1 min"
    if minutes < 60:
        return f"{minutes} min"
    return f"{minutes // 60} h {minutes % 60} min"


def spoken_languages(meeting: Meeting) -> str:
    codes = dict.fromkeys(code for channel in meeting.languages.values() for code in channel)
    return ", ".join(LANGUAGE_NAMES.get(code, code) for code in codes) or "unknown"


def render_markdown(meeting: Meeting, lines: Sequence[Line]) -> str:
    summary = " · ".join(
        [f"{meeting.started_at:%Y-%m-%d %H:%M}", format_duration(meeting.duration or 0), ", ".join(participants(lines))]
    )
    body = "\n\n".join(f"[{format_timestamp(line.start)}] **{line.speaker}:** {line.text}" for line in lines)
    return f"# Transcript — {meeting.title}\n\n{summary}\n\n{body}\n"


def render_plain(lines: Sequence[Line]) -> str:
    return "\n".join(f"[{format_timestamp(line.start)}] {line.speaker}: {line.text}" for line in lines)
