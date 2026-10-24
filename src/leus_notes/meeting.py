from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

META_FILE = "meta.json"


class MeetingNotFound(Exception):
    pass


def now() -> datetime:
    return datetime.now().astimezone()


def slugify(title: str, max_length: int = 60) -> str:
    folded = unicodedata.normalize("NFKD", title.replace("đ", "d").replace("Đ", "D"))
    slug = re.sub(r"[^a-z0-9]+", "-", folded.encode("ascii", "ignore").decode().lower()).strip("-")
    return slug[:max_length].rstrip("-") or "meeting"


def write_json(path: Path, data: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n")
    os.replace(temporary, path)


@dataclass
class Meeting:
    folder: Path
    title: str
    started_at: datetime
    people: str = "auto"
    stopped_at: datetime | None = None
    duration: float | None = None
    languages: dict[str, list[str]] = field(default_factory=dict)
    names: dict[str, str] = field(default_factory=dict)
    devices: dict[str, str] = field(default_factory=dict)
    keep_audio_reason: str | None = None

    @property
    def me_audio(self) -> Path:
        return self.folder / "me.flac"

    @property
    def them_audio(self) -> Path:
        return self.folder / "them.flac"

    @property
    def segments_path(self) -> Path:
        return self.folder / "segments.json"

    @property
    def words_path(self) -> Path:
        return self.folder / "them-words.json"

    @property
    def transcript_path(self) -> Path:
        return self.folder / "transcript.md"

    @property
    def notes_path(self) -> Path:
        return self.folder / "notes.md"

    def has_audio(self) -> bool:
        return self.me_audio.exists() or self.them_audio.exists()

    def has_complete_audio(self) -> bool:
        return self.me_audio.exists() and self.them_audio.exists()

    def delete_audio(self) -> None:
        self.me_audio.unlink(missing_ok=True)
        self.them_audio.unlink(missing_ok=True)

    def save(self) -> None:
        write_json(
            self.folder / META_FILE,
            {
                "title": self.title,
                "started_at": self.started_at.isoformat(),
                "stopped_at": self.stopped_at.isoformat() if self.stopped_at else None,
                "people": self.people,
                "duration": self.duration,
                "languages": self.languages,
                "names": self.names,
                "devices": self.devices,
                "keep_audio_reason": self.keep_audio_reason,
            },
        )

    @classmethod
    def load(cls, folder: Path) -> Meeting:
        data = json.loads((folder / META_FILE).read_text())
        return cls(
            folder=folder,
            title=data["title"],
            started_at=datetime.fromisoformat(data["started_at"]),
            people=data.get("people", "auto"),
            stopped_at=datetime.fromisoformat(data["stopped_at"]) if data.get("stopped_at") else None,
            duration=data.get("duration"),
            languages=data.get("languages", {}),
            names=data.get("names", {}),
            devices=data.get("devices", {}),
            keep_audio_reason=data.get("keep_audio_reason"),
        )

    @classmethod
    def create(cls, meetings_dir: Path, title: str, started_at: datetime, people: str, devices: dict[str, str]) -> Meeting:
        base = f"{started_at:%Y-%m-%d_%H%M}_{slugify(title)}"
        folder = meetings_dir / base
        suffix = 2
        while folder.exists():
            folder = meetings_dir / f"{base}-{suffix}"
            suffix += 1
        meetings_dir.mkdir(parents=True, exist_ok=True)
        folder.mkdir(mode=0o700)
        meeting = cls(folder=folder, title=title, started_at=started_at, people=people, devices=devices)
        meeting.save()
        return meeting


def all_meetings(meetings_dir: Path) -> list[Meeting]:
    meetings = []
    for meta in sorted(meetings_dir.glob(f"*/{META_FILE}"), reverse=True):
        try:
            meetings.append(Meeting.load(meta.parent))
        except (OSError, ValueError, KeyError):
            continue
    return meetings


def find_meeting(
    meetings_dir: Path,
    reference: str | None = None,
    *,
    transcribed: bool = False,
    skip: Path | None = None,
) -> Meeting:
    if reference:
        for candidate in (Path(reference).expanduser(), meetings_dir / reference):
            if (candidate / META_FILE).exists():
                return Meeting.load(candidate.resolve())
        raise MeetingNotFound(f"No meeting found at '{reference}'.")
    for meeting in all_meetings(meetings_dir):
        if meeting.folder.resolve() == skip:
            continue
        if not transcribed or meeting.segments_path.exists():
            return meeting
    raise MeetingNotFound("No transcribed meetings yet." if transcribed else "No meetings yet.")


def sweep_audio(meetings_dir: Path, keep_days: int, moment: datetime) -> list[Meeting]:
    if keep_days < 0:
        return []
    swept = []
    for meeting in all_meetings(meetings_dir):
        if not meeting.has_audio() or not meeting.notes_path.exists() or meeting.keep_audio_reason:
            continue
        if moment - (meeting.stopped_at or meeting.started_at) >= timedelta(days=keep_days):
            meeting.delete_audio()
            swept.append(meeting)
    return swept
