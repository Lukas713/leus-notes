import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import pytest

from leus_notes import notes
from leus_notes.meeting import Meeting
from leus_notes.notes import NotesError, ask_claude, claude_command, claude_environment, notes_request, render_notes
from leus_notes.people import PeopleCount
from leus_notes.transcript import Line

PROJECT = Path(__file__).resolve().parents[1]
SUBSCRIPTION = json.dumps({"loggedIn": True, "authMethod": "claude.ai", "subscriptionType": "max"})


def meeting():
    return Meeting(
        folder=Path("/tmp/x"),
        title="Sample call",
        started_at=datetime(2026, 10, 24, 14, 0, tzinfo=timezone.utc),
        duration=1800,
        languages={"me": ["hr"]},
    )


def test_command_uses_subscription_safe_mode_without_tools():
    command = claude_command("opus", "PROMPT")
    assert command[:2] == ["claude", "-p"]
    assert "--safe-mode" in command
    assert "--bare" not in command
    assert command[command.index("--tools") + 1] == ""
    assert command[command.index("--system-prompt") + 1] == "PROMPT"
    assert command[command.index("--output-format") + 1] == "json"


def test_environment_never_carries_api_settings():
    environment = claude_environment(
        {
            "ANTHROPIC_API_KEY": "k",
            "ANTHROPIC_AUTH_TOKEN": "t",
            "ANTHROPIC_BASE_URL": "https://proxy",
            "CLAUDE_CODE_USE_BEDROCK": "1",
            "CLAUDE_CODE_USE_VERTEX": "1",
            "PATH": "/bin",
        }
    )
    assert environment == {"PATH": "/bin"}


def test_system_prompt_fills_placeholders():
    prompt = notes.system_prompt(PROJECT / "prompts", "English", "Lukas")
    assert "in English" in prompt
    assert '"Lukas" is the person who recorded' in prompt
    assert "when other speakers mention Lukas, they mean this person" in prompt
    assert "{" not in prompt


def test_request_contains_context_and_transcript():
    request = notes_request(meeting(), [Line(3, "Me", "Bok."), Line(9, "Speaker 1", "Hi.")], PeopleCount.parse("2"))
    assert "Meeting title: Sample call" in request
    assert "Number of people who spoke: 2" in request
    assert "Speakers in the transcript: Me, Speaker 1" in request
    assert "Spoken language(s): Croatian" in request
    assert request.endswith("[00:00:03] Me: Bok.\n[00:00:09] Speaker 1: Hi.")


class FakeClaude:
    def __init__(self, answer, returncode=0, auth=SUBSCRIPTION):
        self.answer = answer
        self.returncode = returncode
        self.auth = auth
        self.calls = []

    def __call__(self, command, **kwargs):
        self.calls.append((command, kwargs))
        if command[:3] == ["claude", "auth", "status"]:
            return subprocess.CompletedProcess(command, 0, stdout=self.auth, stderr="")
        return subprocess.CompletedProcess(command, self.returncode, stdout=self.answer, stderr="boom")


def ask():
    return ask_claude("transcript", model="opus", prompt="p", cwd=Path("/tmp"), timeout=5)


def test_ask_claude_checks_the_login_then_returns_the_notes(monkeypatch):
    fake = FakeClaude(json.dumps({"is_error": False, "result": "## Summary\nDone."}))
    monkeypatch.setattr(subprocess, "run", fake)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-pass")
    assert ask() == "## Summary\nDone."
    (auth_command, auth_kwargs), (notes_command, notes_kwargs) = fake.calls
    assert auth_command == ["claude", "auth", "status"]
    assert notes_command[:2] == ["claude", "-p"]
    assert notes_kwargs["input"] == "transcript"
    assert "ANTHROPIC_API_KEY" not in notes_kwargs["env"]
    assert "ANTHROPIC_API_KEY" not in auth_kwargs["env"]


@pytest.mark.parametrize(
    "auth",
    [
        json.dumps({"loggedIn": True, "authMethod": "api_key"}),
        json.dumps({"loggedIn": False}),
        "not json",
    ],
)
def test_ask_claude_refuses_without_a_subscription_login(monkeypatch, auth):
    fake = FakeClaude(json.dumps({"is_error": False, "result": "x"}), auth=auth)
    monkeypatch.setattr(subprocess, "run", fake)
    with pytest.raises(NotesError):
        ask()
    assert len(fake.calls) == 1


@pytest.mark.parametrize(
    ("answer", "returncode"),
    [
        (json.dumps({"is_error": True, "result": "Claude AI usage limit reached"}), 1),
        (json.dumps({"is_error": False, "result": ""}), 0),
        ("not json", 1),
    ],
)
def test_ask_claude_failures(monkeypatch, answer, returncode):
    monkeypatch.setattr(subprocess, "run", FakeClaude(answer, returncode))
    with pytest.raises(NotesError):
        ask()


def test_render_notes_adds_header():
    rendered = render_notes(meeting(), [Line(0, "Me", "x"), Line(1, "Marko", "y")], "## Summary\nShort.\n")
    assert rendered.startswith("# Sample call\n\n- **Date:** 2026-10-24 14:00\n- **Duration:** 30 min\n")
    assert "- **Speakers:** Me, Marko\n" in rendered
    assert rendered.endswith("## Summary\nShort.\n")
