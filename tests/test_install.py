"""Offline deployment regression tests: no access to real ~/.config or KDE."""
import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load_script(name):
    directory = ROOT / "scripts"
    sys.path.insert(0, str(directory))
    spec = importlib.util.spec_from_file_location(name, directory / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

install = load_script("install")
verify = load_script("verify_install")


def test_installation_isolated_idempotent_and_verified(tmp_path):
    home = tmp_path / "user"
    home.mkdir()
    expected = install.install(ROOT, home, environ={})
    p = install.paths(home, {})
    assert p["release"].exists()
    assert p["current"].is_symlink()
    assert p["current"].resolve() == p["release"].resolve()
    assert p["exe"].stat().st_mode & 0o111
    assert expected["desktop"] == str(p["desktop"])
    assert "Name=KDE Dynamic Themes" in p["desktop"].read_text()
    assert "Exec=" in p["desktop"].read_text()
    assert not verify.inspect(home, env={})
    install.install(ROOT, home, environ={})
    assert not verify.inspect(home, env={})


def test_current_symlink_accepts_home_path_alias(tmp_path):
    canonical_home = tmp_path / "var-home" / "ozono"
    canonical_home.mkdir(parents=True)
    alias_home = tmp_path / "home" / "ozono"
    alias_home.parent.mkdir()
    alias_home.symlink_to(canonical_home, target_is_directory=True)

    p = install.paths(alias_home, {})
    p["release"].mkdir(parents=True)
    (p["release"] / ".kdt-release.json").write_text('{"version":"3.0.0"}\n')
    p["current"].symlink_to(p["release"])

    install.check_existing_current(p)


def test_install_refuses_overwriting_unmanaged_launcher(tmp_path):
    home = tmp_path / "user"
    home.mkdir()
    p = install.paths(home, {})
    p["desktop"].parent.mkdir(parents=True)
    p["desktop"].write_text("Non-KDT desktop file\n")
    with pytest.raises(RuntimeError, match="unmanaged"):
        install.install(ROOT, home, environ={})
    assert not p["release"].exists()
    assert p["desktop"].read_text() == "Non-KDT desktop file\n"


def test_tampered_release_is_not_replaced(tmp_path):
    home = tmp_path / "user"
    home.mkdir()
    install.install(ROOT, home, environ={})
    p = install.paths(home, {})
    (p["release"] / "src/kde_dynamic_themes/ui.py").write_text("tampered")
    with pytest.raises(RuntimeError, match="differ"):
        install.install(ROOT, home, environ={})
    assert verify.inspect(home, env={})


def test_git_package_does_not_ship_personal_data():
    assert not (ROOT / "wallpapers").exists()
    assert not (ROOT / "backups").exists()
    assert not (ROOT / "bin").exists()
    assert not any((ROOT / "src").rglob("*.profile"))
