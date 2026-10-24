from __future__ import annotations

import os
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
CONFIG_FILE = "config.toml"
ENV_FILE = ".env"


class ConfigError(Exception):
    pass


@dataclass(frozen=True)
class Settings:
    root: Path = PROJECT_ROOT
    me_label: str = "Me"
    call_outputs: str = "all"
    min_duration_seconds: int = 10
    auto_stop_silence_minutes: float = 0.0
    silence_threshold_db: float = -35.0
    keep_audio_days: int = 0
    whisper_model: str = "large-v3"
    device: str = "auto"
    language: str = "auto"
    languages: tuple[str, ...] = ("en", "hr")
    diarization_model: str = "pyannote/speaker-diarization-community-1"
    claude_model: str = "opus"
    notes_language: str = "English"
    claude_timeout_seconds: int = 600
    meetings_dir: Path = PROJECT_ROOT / "meetings"
    hf_token: str | None = None

    @property
    def run_dir(self) -> Path:
        return self.root / "run"

    @property
    def models_dir(self) -> Path:
        return self.root / "models"

    @property
    def prompts_dir(self) -> Path:
        return self.root / "prompts"


CONFIG_KEYS: dict[tuple[str, str], str] = {
    ("recording", "me_label"): "me_label",
    ("recording", "outputs"): "call_outputs",
    ("recording", "min_duration_seconds"): "min_duration_seconds",
    ("recording", "auto_stop_silence_minutes"): "auto_stop_silence_minutes",
    ("recording", "silence_threshold_db"): "silence_threshold_db",
    ("audio", "keep_days"): "keep_audio_days",
    ("transcription", "model"): "whisper_model",
    ("transcription", "device"): "device",
    ("transcription", "language"): "language",
    ("transcription", "languages"): "languages",
    ("speakers", "model"): "diarization_model",
    ("notes", "claude_model"): "claude_model",
    ("notes", "language"): "notes_language",
    ("notes", "timeout_seconds"): "claude_timeout_seconds",
    ("paths", "meetings_dir"): "meetings_dir",
}

CHOICES: dict[str, tuple[str, ...]] = {
    "call_outputs": ("all", "default"),
    "device": ("auto", "cuda", "cpu"),
}


def load_settings(root: Path = PROJECT_ROOT, environ: Mapping[str, str] = os.environ) -> Settings:
    values: dict[str, object] = {"root": root, "meetings_dir": root / "meetings"}
    config_path = root / CONFIG_FILE
    if config_path.exists():
        values.update(parse_config(config_path, root))
    values["hf_token"] = environ.get("HF_TOKEN") or read_env_file(root / ENV_FILE).get("HF_TOKEN") or None
    return Settings(**values)


def parse_config(path: Path, root: Path) -> dict[str, object]:
    try:
        data = tomllib.loads(path.read_text())
    except tomllib.TOMLDecodeError as error:
        raise ConfigError(f"{path}: {error}") from error
    defaults = Settings()
    values: dict[str, object] = {}
    unknown: list[str] = []
    for section, table in data.items():
        if not isinstance(table, dict):
            unknown.append(section)
            continue
        for key, value in table.items():
            name = CONFIG_KEYS.get((section, key))
            if name is None:
                unknown.append(f"{section}.{key}")
                continue
            values[name] = coerce(f"{section}.{key}", value, getattr(defaults, name), path, root)
            if name in CHOICES and values[name] not in CHOICES[name]:
                raise ConfigError(f"{path}: {section}.{key} must be one of {', '.join(CHOICES[name])}, got {value!r}")
    if unknown:
        raise ConfigError(f"{path}: unknown setting(s): {', '.join(unknown)}")
    return values


def coerce(key: str, value: object, default: object, path: Path, root: Path) -> object:
    if isinstance(default, Path) and isinstance(value, str):
        candidate = Path(value).expanduser()
        return candidate if candidate.is_absolute() else root / candidate
    if isinstance(default, tuple) and isinstance(value, list) and all(isinstance(item, str) for item in value):
        return tuple(value)
    if isinstance(default, float) and isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if isinstance(default, int) and isinstance(value, int) and not isinstance(value, bool):
        return value
    if isinstance(default, str) and isinstance(value, str):
        return value
    raise ConfigError(f"{path}: {key} must be {describe(default)}, got {value!r}")


def describe(default: object) -> str:
    if isinstance(default, Path):
        return "a path"
    if isinstance(default, tuple):
        return "a list of strings"
    if isinstance(default, float):
        return "a number"
    if isinstance(default, int):
        return "a whole number"
    return "text"


def read_env_file(path: Path) -> dict[str, str]:
    if not path.exists():
        return {}
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("'\"")
    return values
