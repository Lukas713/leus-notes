#!/usr/bin/env python3
from __future__ import annotations

import argparse
import getpass
import importlib
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV = ROOT / ".venv"
VENV_PYTHON = VENV / "bin" / "python"
LAUNCHER = ROOT / "leus-notes"
LINK = Path.home() / ".local" / "bin" / "leus-notes"
ENV_FILE = ROOT / ".env"
CONFIG_FILE = ROOT / "config.toml"
EXAMPLE_CONFIG = ROOT / "config.example.toml"
SPEAKER_MODEL_URL = "https://huggingface.co/pyannote/speaker-diarization-community-1"
MINIMUM_PYTHON = (3, 11)
PIP = ["-m", "pip", "install", "--no-cache-dir", "--disable-pip-version-check"]


class InstallError(Exception):
    pass


def project_module(name: str):
    if str(ROOT / "src") not in sys.path:
        sys.path.insert(0, str(ROOT / "src"))
    return importlib.import_module(f"leus_notes.{name}")


def step(message: str) -> None:
    print(f"\n→ {message}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Install leus-notes: packages, models, configuration and the command.")
    parser.add_argument("--skip-models", action="store_true", help="don't download the models now (they download on first use)")
    parser.add_argument("--force", action="store_true", help=f"replace an existing {LINK}")
    parser.add_argument("--uninstall", action="store_true", help=f"remove {LINK}")
    parser.add_argument("--purge", action="store_true", help="with --uninstall: also delete .venv, models and caches (never meetings)")
    args = parser.parse_args(argv)
    try:
        if args.uninstall:
            uninstall(args.purge)
        else:
            install(args.skip_models, args.force)
    except InstallError as error:
        print(f"\n✗ {error}", file=sys.stderr)
        return 1
    return 0


def install(skip_models: bool, force: bool) -> None:
    step("Checking the system")
    check_system()
    gpu = has_nvidia_gpu()

    step("Installing Python packages into .venv (several GB the first time)")
    create_venv()
    pip_install("-r", "requirements.txt", *(["-r", "requirements-gpu.txt"] if gpu else []))

    step("Configuration")
    ensure_config()
    ensure_hf_token()
    for folder in ("meetings", "run", "models"):
        (ROOT / folder).mkdir(exist_ok=True)

    step("Checking the setup" if skip_models else "Downloading and testing the models (about 4 GB the first time)")
    doctor = subprocess.run([str(VENV_PYTHON), str(LAUNCHER), "doctor", *([] if skip_models else ["--download-models"])])
    if doctor.returncode != 0:
        raise InstallError("Some required checks failed (marked ✗ above). Fix them and run python3 install.py again.")

    step("Linking the command")
    make_executable(LAUNCHER)
    print(f"  {ensure_link(LINK, LAUNCHER, force)}")
    if str(LINK.parent) not in os.environ.get("PATH", "").split(os.pathsep):
        print(f"  ! {LINK.parent} is not on your PATH; add it to use `leus-notes` from any terminal.")

    print('\nDone. Start a recording with:\n  leus-notes start "Discussion about sample" --number-of-people=2')


def check_python() -> None:
    if sys.version_info < MINIMUM_PYTHON:
        raise InstallError(f"Python {'.'.join(map(str, MINIMUM_PYTHON))} or newer is needed (this is {sys.version.split()[0]}).")
    print(f"  ✓ Python {sys.version.split()[0]}")


def check_system() -> None:
    check_python()
    doctor = project_module("doctor")
    checks = [
        doctor.command_check("ffmpeg", "ffmpeg", "install it with: sudo apt install ffmpeg"),
        doctor.command_check("pactl", "PipeWire tools", "install it with: sudo apt install pulseaudio-utils"),
        doctor.command_check("notify-send", "Desktop notifications", "install libnotify-bin", required=False),
        doctor.claude_check(),
        doctor.api_key_check(),
    ]
    if not all([doctor.report(check) for check in checks]):
        raise InstallError("Fix the items marked ✗ above and run python3 install.py again.")


def has_nvidia_gpu() -> bool:
    try:
        result = subprocess.run(["nvidia-smi", "-L"], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError):
        result = None
    if result is None or result.returncode != 0 or "GPU" not in result.stdout:
        print("  ! No NVIDIA GPU found: transcription will run on the CPU (much slower).")
        return False
    print(f"  ✓ {result.stdout.splitlines()[0].split(' (UUID')[0]}")
    return True


def create_venv() -> None:
    try:
        if not VENV_PYTHON.exists():
            subprocess.run([sys.executable, "-m", "venv", str(VENV)], check=True)
        subprocess.run([str(VENV_PYTHON), *PIP, "--quiet", "--upgrade", "pip"], check=True)
    except subprocess.CalledProcessError as error:
        raise InstallError(f"Creating the virtual environment failed: {error}") from error


def pip_install(*requirements: str) -> None:
    try:
        subprocess.run([str(VENV_PYTHON), *PIP, *requirements], cwd=ROOT, check=True)
    except subprocess.CalledProcessError as error:
        raise InstallError(f"Installing the Python packages failed: {error}") from error


def ensure_config() -> None:
    if CONFIG_FILE.exists():
        print(f"  ✓ kept your {CONFIG_FILE.name}")
        return
    shutil.copyfile(EXAMPLE_CONFIG, CONFIG_FILE)
    print(f"  ✓ created {CONFIG_FILE.name} (edit it to change the defaults)")


def ensure_hf_token() -> None:
    saved = project_module("config").read_env_file(ENV_FILE).get("HF_TOKEN")
    token = os.environ.get("HF_TOKEN") or saved
    if not token and sys.stdin.isatty():
        print(
            "  Speaker separation (Speaker 1, Speaker 2, …) uses a free model that needs a Hugging Face token:\n"
            "    1. create an account at https://huggingface.co/join\n"
            f"    2. accept the model's conditions at {SPEAKER_MODEL_URL}\n"
            "    3. create a read token at https://huggingface.co/settings/tokens"
        )
        token = getpass.getpass("  Hugging Face token (Enter to skip): ").strip()
    if not token:
        print("  ! No Hugging Face token: calls with 3+ people label everyone else 'Them' until you add one.")
        return
    if token == saved:
        print(f"  ✓ Hugging Face token found in {ENV_FILE.name}")
        return
    write_env_value(ENV_FILE, "HF_TOKEN", token)
    print(f"  ✓ Hugging Face token saved to {ENV_FILE.name}")


def write_env_value(path: Path, key: str, value: str) -> None:
    lines = path.read_text().splitlines() if path.exists() else []
    kept = [line for line in lines if not line.strip().startswith(f"{key}=")]
    if path.exists():
        path.chmod(0o600)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w") as handle:
        handle.write("\n".join([*kept, f"{key}={value}"]) + "\n")


def make_executable(path: Path) -> None:
    path.chmod(path.stat().st_mode | 0o111)


def ensure_link(link: Path, target: Path, force: bool) -> str:
    if link.is_symlink() and link.resolve() == target.resolve():
        return f"✓ {link} already points to {target}"
    if link.is_symlink() or link.exists():
        if not force:
            raise InstallError(f"{link} already exists and is not leus-notes. Use --force to replace it.")
        link.unlink()
    link.parent.mkdir(parents=True, exist_ok=True)
    link.symlink_to(target)
    return f"✓ linked {link} → {target}"


def remove_link(link: Path, target: Path) -> bool:
    if link.is_symlink() and link.resolve() == target.resolve():
        link.unlink()
        return True
    return False


def uninstall(purge: bool) -> None:
    step("Uninstalling leus-notes")
    print(f"  ✓ removed {LINK}" if remove_link(LINK, LAUNCHER) else f"  - {LINK} was not linked to leus-notes")
    if not purge:
        return
    for path in (VENV, ROOT / "models", ROOT / ".cache"):
        if path.exists():
            shutil.rmtree(path)
            print(f"  ✓ deleted {path}")
    print("  Kept meetings/, config.toml and .env.")


if __name__ == "__main__":
    sys.exit(main())
