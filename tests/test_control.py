import os
import subprocess
import sys
import time
from pathlib import Path

from leus_notes import control
from leus_notes.control import ActiveRecording, StopRequest


def recording(pid):
    return ActiveRecording(pid=pid, folder="/x", title="Call", started_at="2026-10-24T14:00:00+00:00", people="3")


def test_active_recording_round_trip(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "is_leus_notes_process", lambda pid: True)
    control.write_active(tmp_path, recording(os.getpid()))
    assert control.read_active(tmp_path) == recording(os.getpid())
    control.clear_active(tmp_path)
    assert control.read_active(tmp_path) is None


def test_stale_recording_is_removed(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "is_leus_notes_process", lambda pid: False)
    control.write_active(tmp_path, recording(999999))
    assert control.read_active(tmp_path) is None
    assert not (tmp_path / control.ACTIVE_FILE).exists()


def test_corrupt_recording_file_is_removed(tmp_path):
    (tmp_path / control.ACTIVE_FILE).write_text("{not json")
    assert control.read_active(tmp_path) is None


def started(process):
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and not Path(f"/proc/{process.pid}/cmdline").read_bytes():
        time.sleep(0.01)
    return process


def test_only_leus_notes_processes_count():
    other = started(subprocess.Popen(["sleep", "30"]))
    ours = started(subprocess.Popen([sys.executable, "-c", "import time; time.sleep(30)", "leus-notes", "start"]))
    try:
        assert not control.is_leus_notes_process(other.pid)
        assert control.is_leus_notes_process(ours.pid)
        assert not control.is_leus_notes_process(999999999)
    finally:
        for process in (other, ours):
            process.kill()
            process.wait()


def test_stop_request_is_taken_once(tmp_path):
    control.write_stop_request(tmp_path, StopRequest(discard=False, people="4"))
    assert control.take_stop_request(tmp_path) == StopRequest(discard=False, people="4")
    assert control.take_stop_request(tmp_path) is None


def test_starting_clears_a_leftover_stop_request(tmp_path, monkeypatch):
    monkeypatch.setattr(control, "is_leus_notes_process", lambda pid: True)
    control.write_stop_request(tmp_path, StopRequest(discard=True))
    control.write_active(tmp_path, recording(os.getpid()))
    assert control.take_stop_request(tmp_path) is None
