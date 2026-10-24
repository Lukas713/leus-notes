from __future__ import annotations

import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

from .config import Settings
from .notes import BLOCKED_ENVIRONMENT_PREFIXES, SUBSCRIPTION_AUTH, auth_status
from .recorder import RecordingError, default_devices


@dataclass(frozen=True)
class Check:
    name: str
    ok: bool
    detail: str
    required: bool = True


def run(settings: Settings, download_models: bool = False) -> int:
    checks: list[Callable[[], Check]] = [
        lambda: command_check("ffmpeg", "ffmpeg", "install it with: sudo apt install ffmpeg"),
        lambda: devices_check(settings),
        lambda: command_check("notify-send", "Desktop notifications", "install libnotify-bin", required=False),
        claude_check,
        api_key_check,
        gpu_check,
        lambda: whisper_check(settings, download_models),
        lambda: hf_token_check(settings),
        lambda: speaker_model_check(settings, download_models),
    ]
    passed = [report(check()) for check in checks]
    return 0 if all(passed) else 1


def report(check: Check) -> bool:
    mark = "✓" if check.ok else ("✗" if check.required else "!")
    print(f"  {mark} {check.name}: {check.detail}", flush=True)
    return check.ok or not check.required


def command_check(command: str, name: str, hint: str, required: bool = True) -> Check:
    path = shutil.which(command)
    return Check(name, bool(path), path or f"not found — {hint}", required)


def devices_check(settings: Settings) -> Check:
    try:
        devices = default_devices(all_outputs=settings.call_outputs == "all")
    except RecordingError as error:
        return Check("Audio devices", False, str(error))
    outputs = len(devices.monitors)
    return Check("Audio devices", True, f"mic {devices.mic} · call audio from {outputs} output device(s)")


def claude_check() -> Check:
    if not shutil.which("claude"):
        return Check("Claude Code", False, "`claude` not found — install Claude Code and log in with your subscription")
    try:
        status = auth_status()
    except (OSError, subprocess.SubprocessError, json.JSONDecodeError) as error:
        return Check("Claude Code", False, f"could not read `claude auth status`: {error}")
    if not status.get("loggedIn"):
        return Check("Claude Code", False, "not logged in — run `claude` and use /login with your subscription")
    if status.get("authMethod") != SUBSCRIPTION_AUTH:
        return Check("Claude Code", False, f"logged in via {status.get('authMethod')}, not a Claude subscription")
    return Check("Claude Code", True, f"logged in with claude.ai ({status.get('subscriptionType', 'subscription')})")


def api_key_check() -> Check:
    found = sorted(key for key in os.environ if key.startswith(BLOCKED_ENVIRONMENT_PREFIXES))
    if found:
        return Check("API settings", False, f"{', '.join(found)} set; leus-notes removes them for note calls", required=False)
    return Check("API settings", True, "none set — notes always use the subscription", required=False)


def gpu_check() -> Check:
    try:
        import ctranslate2
    except ImportError:
        return Check("GPU", False, "faster-whisper is not installed — run python3 install.py")
    count = ctranslate2.get_cuda_device_count()
    if count:
        return Check("GPU", True, f"{count} CUDA device(s) available", required=False)
    return Check("GPU", False, "no CUDA device — transcription runs on the CPU (much slower)", required=False)


def whisper_check(settings: Settings, download: bool) -> Check:
    from .transcriber import Transcriber

    name = "Speech model"
    cached = any((settings.models_dir / "whisper").glob(f"models--*--faster-whisper-{settings.whisper_model}"))
    if not cached and not download:
        return Check(name, False, f"{settings.whisper_model} not downloaded yet — downloads on first use", required=False)
    try:
        transcriber = Transcriber(
            settings.whisper_model, settings.device, settings.models_dir / "whisper", settings.language, settings.languages
        )
        transcriber.self_test()
    except Exception as error:
        return Check(name, False, f"{type(error).__name__}: {error}")
    device = transcriber.device
    transcriber.close()
    return Check(name, True, f"{settings.whisper_model} works on {device}")


def hf_token_check(settings: Settings) -> Check:
    if settings.hf_token:
        return Check("Hugging Face token", True, "configured", required=False)
    return Check(
        "Hugging Face token",
        False,
        "missing — calls with 3+ people won't get Speaker 1…N (add HF_TOKEN to .env, see README)",
        required=False,
    )


def speaker_model_check(settings: Settings, download: bool) -> Check:
    name = "Speaker model"
    if not settings.hf_token:
        return Check(name, False, "skipped (no Hugging Face token)", required=False)
    if not download:
        return access_check(settings)
    from .diarizer import DiarizationError, load_pipeline

    try:
        pipeline = load_pipeline(settings.diarization_model, settings.hf_token)
    except DiarizationError as error:
        return Check(name, False, str(error), required=False)
    return Check(name, True, f"{settings.diarization_model} loaded on {getattr(pipeline, 'device', 'cpu')}", required=False)


def access_check(settings: Settings) -> Check:
    from huggingface_hub import auth_check
    from huggingface_hub.errors import GatedRepoError, HfHubHTTPError

    name = "Speaker model"
    try:
        auth_check(settings.diarization_model, token=settings.hf_token)
    except GatedRepoError:
        url = f"https://huggingface.co/{settings.diarization_model}"
        return Check(name, False, f"accept the model's conditions at {url}", required=False)
    except HfHubHTTPError as error:
        return Check(name, False, f"Hugging Face refused access: {error}", required=False)
    return Check(name, True, f"access to {settings.diarization_model} granted", required=False)
