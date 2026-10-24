import pytest

from leus_notes.cli import UserError, decide_after_stop, split_names_arguments
from leus_notes.config import Settings
from leus_notes.control import StopRequest
from leus_notes.people import PeopleCount
from leus_notes.recorder import RecordingResult, StopReason


def test_split_names_arguments():
    assert split_names_arguments(["2026-10-24_1400_call", "Speaker 1=Marko", "2 = Ana Horvat", "speaker 3="]) == (
        "2026-10-24_1400_call",
        [("1", "Marko"), ("2", "Ana Horvat"), ("3", "")],
    )
    assert split_names_arguments([]) == (None, [])


@pytest.mark.parametrize("items", [["Marko=1"], ["one", "two"]])
def test_split_names_arguments_rejects(items):
    with pytest.raises(UserError):
        split_names_arguments(items)


THREE = PeopleCount.parse("3")


def test_stop_command_request_overrides_count():
    result = RecordingResult(StopReason.STOP_COMMAND, 600)
    assert decide_after_stop(result, StopRequest(people="4"), THREE, Settings()) == PeopleCount.parse("4")
    assert decide_after_stop(result, StopRequest(), THREE, Settings()) == THREE
    assert decide_after_stop(result, None, THREE, Settings()) == THREE
    assert decide_after_stop(result, StopRequest(discard=True), THREE, Settings()) is None


def test_silence_keeps_start_count():
    result = RecordingResult(StopReason.SILENCE, 600)
    assert decide_after_stop(result, None, THREE, Settings(auto_stop_silence_minutes=5)) == THREE


def test_interrupt_asks_for_count(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    answers = iter(["seven people", "4"])
    monkeypatch.setattr("builtins.input", lambda prompt: next(answers))
    result = RecordingResult(StopReason.INTERRUPTED, 600)
    assert decide_after_stop(result, None, THREE, Settings()) == PeopleCount.parse("4")


def test_interrupt_enter_keeps_count(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert decide_after_stop(RecordingResult(StopReason.INTERRUPTED, 600), None, THREE, Settings()) == THREE


def test_short_recording_offers_discard(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt: "")
    assert decide_after_stop(RecordingResult(StopReason.INTERRUPTED, 4), None, THREE, Settings()) is None


def test_without_terminal_no_questions():
    assert decide_after_stop(RecordingResult(StopReason.INTERRUPTED, 4), None, THREE, Settings()) == THREE
