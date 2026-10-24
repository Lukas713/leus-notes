import pytest

from leus_notes.config import ConfigError, load_settings, read_env_file


def test_defaults_without_config(tmp_path):
    settings = load_settings(tmp_path, environ={})
    assert settings.keep_audio_days == 0
    assert settings.me_label == "Me"
    assert settings.languages == ("en", "hr")
    assert settings.meetings_dir == tmp_path / "meetings"
    assert settings.hf_token is None


def test_config_overrides(tmp_path):
    (tmp_path / "config.toml").write_text(
        '[audio]\nkeep_days = 14\n[recording]\nauto_stop_silence_minutes = 5\nme_label = "Lukas"\n'
        '[transcription]\nlanguages = ["hr"]\n[paths]\nmeetings_dir = "/srv/notes"\n'
    )
    settings = load_settings(tmp_path, environ={})
    assert settings.keep_audio_days == 14
    assert settings.auto_stop_silence_minutes == 5.0
    assert settings.me_label == "Lukas"
    assert settings.languages == ("hr",)
    assert str(settings.meetings_dir) == "/srv/notes"


def test_relative_meetings_dir_is_inside_project(tmp_path):
    (tmp_path / "config.toml").write_text('[paths]\nmeetings_dir = "archive"\n')
    assert load_settings(tmp_path, environ={}).meetings_dir == tmp_path / "archive"


def test_unknown_setting_is_rejected(tmp_path):
    (tmp_path / "config.toml").write_text("[audio]\nkeep_dayz = 3\n")
    with pytest.raises(ConfigError, match="audio.keep_dayz"):
        load_settings(tmp_path, environ={})


def test_wrong_type_is_rejected(tmp_path):
    (tmp_path / "config.toml").write_text('[audio]\nkeep_days = "forever"\n')
    with pytest.raises(ConfigError, match="whole number"):
        load_settings(tmp_path, environ={})


def test_choice_settings_are_validated(tmp_path):
    (tmp_path / "config.toml").write_text('[recording]\noutputs = "headset"\n')
    with pytest.raises(ConfigError, match="all, default"):
        load_settings(tmp_path, environ={})


def test_token_from_env_file_and_environment(tmp_path):
    (tmp_path / ".env").write_text("# comment\nHF_TOKEN='hf_file'\n")
    assert load_settings(tmp_path, environ={}).hf_token == "hf_file"
    assert load_settings(tmp_path, environ={"HF_TOKEN": "hf_env"}).hf_token == "hf_env"


def test_read_env_file_missing(tmp_path):
    assert read_env_file(tmp_path / ".env") == {}
