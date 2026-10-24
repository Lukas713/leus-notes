from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Mapping, Sequence
from pathlib import Path

from .meeting import Meeting
from .people import PeopleCount
from .transcript import Line, format_duration, participants, render_plain, spoken_languages

SYSTEM_PROMPT_FILE = "notes_system.md"
BLOCKED_ENVIRONMENT_PREFIXES = ("ANTHROPIC_", "CLAUDE_CODE_USE_")
SUBSCRIPTION_AUTH = "claude.ai"


class NotesError(Exception):
    pass


def system_prompt(prompts_dir: Path, notes_language: str, me_label: str) -> str:
    template = (prompts_dir / SYSTEM_PROMPT_FILE).read_text()
    return template.replace("{notes_language}", notes_language).replace("{me_label}", me_label)


def claude_command(model: str, prompt: str) -> list[str]:
    return [
        "claude", "-p",
        "--safe-mode",
        "--model", model,
        "--tools", "",
        "--strict-mcp-config",
        "--disable-slash-commands",
        "--no-session-persistence",
        "--output-format", "json",
        "--system-prompt", prompt,
    ]


def claude_environment(environ: Mapping[str, str] = os.environ) -> dict[str, str]:
    return {key: value for key, value in environ.items() if not key.startswith(BLOCKED_ENVIRONMENT_PREFIXES)}


def auth_status() -> dict:
    result = subprocess.run(
        ["claude", "auth", "status"], capture_output=True, text=True, timeout=30, env=claude_environment()
    )
    return json.loads(result.stdout)


def require_subscription() -> None:
    try:
        status = auth_status()
    except FileNotFoundError as error:
        raise NotesError("the `claude` command was not found. Install Claude Code and log in with your subscription.") from error
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        raise NotesError(f"could not check the Claude login: {error}") from error
    if not status.get("loggedIn") or status.get("authMethod") != SUBSCRIPTION_AUTH:
        raise NotesError(
            "Claude Code is not logged in with a claude.ai subscription, so no notes were requested "
            "(anything else could mean API billing). Run `claude` and use /login."
        )


def notes_request(meeting: Meeting, lines: Sequence[Line], people: PeopleCount) -> str:
    return "\n".join(
        [
            f"Meeting title: {meeting.title}",
            f"Date: {meeting.started_at:%Y-%m-%d %H:%M}",
            f"Duration: {format_duration(meeting.duration or 0)}",
            f"Number of people who spoke: {'not given' if people.is_auto else people}",
            f"Speakers in the transcript: {', '.join(participants(lines))}",
            f"Spoken language(s): {spoken_languages(meeting)}",
            "",
            "Transcript:",
            render_plain(lines),
        ]
    )


def ask_claude(request: str, *, model: str, prompt: str, cwd: Path, timeout: int) -> str:
    require_subscription()
    try:
        result = subprocess.run(
            claude_command(model, prompt),
            input=request,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=cwd,
            env=claude_environment(),
        )
    except FileNotFoundError as error:
        raise NotesError("the `claude` command was not found. Install Claude Code and log in with your subscription.") from error
    except subprocess.TimeoutExpired as error:
        raise NotesError(f"Claude did not answer within {timeout} s.") from error
    try:
        response = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        detail = (result.stderr or result.stdout).strip()[:500]
        raise NotesError(f"Claude failed (exit code {result.returncode}): {detail}") from error
    answer = str(response.get("result") or "").strip()
    if result.returncode != 0 or response.get("is_error") or not answer:
        raise NotesError(f"Claude failed: {answer or response.get('subtype') or result.stderr.strip()}")
    return answer


def render_notes(meeting: Meeting, lines: Sequence[Line], body: str) -> str:
    return "\n".join(
        [
            f"# {meeting.title}",
            "",
            f"- **Date:** {meeting.started_at:%Y-%m-%d %H:%M}",
            f"- **Duration:** {format_duration(meeting.duration or 0)}",
            f"- **Speakers:** {', '.join(participants(lines))}",
            f"- **Spoken language:** {spoken_languages(meeting)}",
            "",
            body.strip(),
            "",
        ]
    )
