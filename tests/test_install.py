import stat

import pytest

import install


def test_ensure_link_creates_and_is_idempotent(tmp_path):
    target = tmp_path / "leus-notes"
    target.write_text("#!/usr/bin/env python3\n")
    link = tmp_path / "bin" / "leus-notes"
    assert "linked" in install.ensure_link(link, target, force=False)
    assert link.resolve() == target
    assert "already points" in install.ensure_link(link, target, force=False)


def test_ensure_link_refuses_foreign_file_unless_forced(tmp_path):
    target = tmp_path / "leus-notes"
    target.write_text("")
    link = tmp_path / "leus-notes-link"
    link.write_text("someone else's script")
    with pytest.raises(install.InstallError):
        install.ensure_link(link, target, force=False)
    install.ensure_link(link, target, force=True)
    assert link.resolve() == target


def test_remove_link_only_removes_our_link(tmp_path):
    target = tmp_path / "leus-notes"
    target.write_text("")
    other = tmp_path / "other"
    other.write_text("")
    link = tmp_path / "link"
    link.symlink_to(other)
    assert not install.remove_link(link, target)
    assert link.exists()
    link.unlink()
    link.symlink_to(target)
    assert install.remove_link(link, target)
    assert not link.exists()


def test_make_executable(tmp_path):
    launcher = tmp_path / "leus-notes"
    launcher.write_text("#!/usr/bin/env python3\n")
    launcher.chmod(0o644)
    install.make_executable(launcher)
    assert stat.S_IMODE(launcher.stat().st_mode) == 0o755


def test_write_env_value_creates_a_private_file(tmp_path):
    env = tmp_path / ".env"
    install.write_env_value(env, "HF_TOKEN", "hf_secret")
    assert env.read_text() == "HF_TOKEN=hf_secret\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600


def test_write_env_value_replaces_key_and_restricts_permissions(tmp_path):
    env = tmp_path / ".env"
    env.write_text("OTHER=1\nHF_TOKEN=old\n")
    install.write_env_value(env, "HF_TOKEN", "hf_new")
    assert env.read_text() == "OTHER=1\nHF_TOKEN=hf_new\n"
    assert stat.S_IMODE(env.stat().st_mode) == 0o600
