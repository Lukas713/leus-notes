from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

from .meeting import write_json

ACTIVE_FILE = "recording.json"
STOP_FILE = "stop.json"


@dataclass(frozen=True)
class ActiveRecording:
    pid: int
    folder: str
    title: str
    started_at: str
    people: str


@dataclass(frozen=True)
class StopRequest:
    discard: bool = False
    people: str | None = None


def is_leus_notes_process(pid: int) -> bool:
    try:
        command_line = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        return False
    return b"leus-notes" in command_line or b"leus_notes" in command_line


def write_active(run_dir: Path, recording: ActiveRecording) -> None:
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / STOP_FILE).unlink(missing_ok=True)
    write_json(run_dir / ACTIVE_FILE, asdict(recording))


def read_active(run_dir: Path) -> ActiveRecording | None:
    path = run_dir / ACTIVE_FILE
    if not path.exists():
        return None
    try:
        recording = ActiveRecording(**json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        path.unlink(missing_ok=True)
        return None
    if not is_leus_notes_process(recording.pid):
        path.unlink(missing_ok=True)
        return None
    return recording


def clear_active(run_dir: Path) -> None:
    (run_dir / ACTIVE_FILE).unlink(missing_ok=True)


def write_stop_request(run_dir: Path, request: StopRequest) -> None:
    write_json(run_dir / STOP_FILE, asdict(request))


def take_stop_request(run_dir: Path) -> StopRequest | None:
    path = run_dir / STOP_FILE
    if not path.exists():
        return None
    try:
        return StopRequest(**json.loads(path.read_text()))
    except (OSError, ValueError, TypeError):
        return None
    finally:
        path.unlink(missing_ok=True)
