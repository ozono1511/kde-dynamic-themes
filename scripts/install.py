#!/usr/bin/env python3
"""Install KDE Dynamic Themes v3 into the user's XDG dirs without root.

Only managed launcher/icon/desktop files and a new versioned code directory are
written. Existing wallpaper library, original app, config, backups and KDE state
are never changed. This script intentionally does NOT install Python packages.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile

VERSION = "3.0.0"
MARKER = "KDT_MANAGED_v3"
ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "src" / "kde_dynamic_themes"
ICON = ROOT / "packaging" / "kde-dynamic-themes.svg"


def paths(home: Path, environ: dict[str, str] | None = None) -> dict[str, Path]:
    env = os.environ if environ is None else environ
    data = Path(env.get("XDG_DATA_HOME") or home / ".local/share").expanduser()
    app_data = data / "kde-dynamic-themes"
    return {
        "data": app_data, "release": app_data / "releases" / VERSION,
        "current": app_data / "current", "exe": home / ".local/bin/kde-dynamic-themes",
        "desktop": data / "applications/kde-dynamic-themes.desktop",
        "icon": data / "icons/hicolor/scalable/apps/kde-dynamic-themes.svg",
    }


def source_hash(pkg: Path) -> str:
    digest = hashlib.sha256()
    for source in sorted(pkg.glob("*.py")):
        digest.update(source.name.encode() + b"\0")
        digest.update(source.read_bytes())
    return digest.hexdigest()


def check_existing_managed(path: Path, marker: str = MARKER) -> None:
    if path.is_symlink():
        raise RuntimeError(f"Refusing to overwrite a symlink: {path}")
    if path.exists():
        if not path.is_file() or marker not in path.read_text(encoding="utf-8"):
            raise RuntimeError(f"Existing unmanaged file will not be overwritten: {path}")


def check_existing_current(p: dict[str, Path]) -> None:
    current = p["current"]
    if not current.exists() and not current.is_symlink():
        return
    if not current.is_symlink():
        raise RuntimeError(f"Current installation path is not a managed symlink: {current}")
    resolved = current.resolve()
    # An existing symlink is managed only if its target has our release manifest.
    if not resolved.is_relative_to(p["data"] / "releases") or not (resolved / ".kdt-release.json").is_file():
        raise RuntimeError(f"Current installation points outside a managed release: {current}")


def preflight(home: Path, env: dict[str, str] | None = None) -> None:
    if os.geteuid() == 0:
        raise RuntimeError("Run as your normal desktop user, without sudo.")
    if not ((3, 12) <= sys.version_info[:2] < (3, 15)):
        raise RuntimeError("Python 3.12–3.14 is required.")
    try:
        importlib.import_module("PySide6.QtWidgets")
    except (ImportError, OSError) as exc:
        raise RuntimeError("PySide6 is not available in this Python environment; installation stopped.") from exc
    project = Path((env or os.environ).get("KDT_PROJECT_ROOT") or home / "Projects/kde-dynamic-themes")
    if not (project / "bin/matugen").is_file() or not os.access(project / "bin/matugen", os.X_OK):
        raise RuntimeError(f"Matugen executable missing: {project / 'bin/matugen'}")
    for cmd in ("plasma-apply-wallpaperimage", "plasma-apply-colorscheme", "kwriteconfig6", "kreadconfig6"):
        if not shutil.which(cmd):
            raise RuntimeError(f"KDE dependency missing: {cmd}")


def wrapper_text() -> str:
    return f'''#!/bin/sh
# {MARKER} — start the locally installed release
set -eu
APP_ROOT="${{XDG_DATA_HOME:-$HOME/.local/share}}/kde-dynamic-themes"
if [ ! -f "$APP_ROOT/current/src/kde_dynamic_themes/__main__.py" ]; then
    echo 'KDE Dynamic Themes installation is incomplete.' >&2
    exit 1
fi
PYTHONPATH="$APP_ROOT/current/src${{PYTHONPATH:+:$PYTHONPATH}}"
export PYTHONPATH
exec python3 -m kde_dynamic_themes "$@"
'''


def desktop_text(executable: Path) -> str:
    # The KDE user launcher path is absolute and shell metacharacters are not used.
    if any(c in str(executable) for c in ('\n', '\r', '"', '\\')):
        raise RuntimeError("Unsupported executable path in desktop launcher.")
    return f'''[Desktop Entry]
Type=Application
Version=1.0
Name=KDE Dynamic Themes
GenericName=Wallpaper and Color Themes
Comment=Apply Matugen colors and wallpapers to KDE Plasma and Konsole
Exec="{executable}"
TryExec={executable}
Icon=kde-dynamic-themes
Terminal=false
Categories=Utility;Settings;DesktopSettings;
StartupNotify=true
X-KDT-Managed={MARKER}
'''


def atomic_text(path: Path, contents: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".kdt-install-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(contents)
        os.chmod(temporary, 0o755 if executable else 0o644)
        os.replace(temporary, path)
    finally:
        if os.path.lexists(temporary):
            os.unlink(temporary)


def install(root: Path, home: Path, *, environ: dict[str, str] | None = None) -> dict[str, str]:
    p = paths(home, environ)
    pkg = root / "src/kde_dynamic_themes"
    icon = root / "packaging/kde-dynamic-themes.svg"
    if not (pkg / "__main__.py").is_file() or not icon.is_file():
        raise RuntimeError("Distribution is incomplete: missing application or icon.")
    for key in ("exe", "desktop", "icon"):
        check_existing_managed(p[key])
    check_existing_current(p)
    expected_hash = source_hash(pkg)
    release = p["release"]
    if release.is_symlink():
        raise RuntimeError("Refusing a symlink in the release directory.")
    if release.exists():
        marker = release / ".kdt-release.json"
        if not marker.is_file() or json.loads(marker.read_text()).get("sha256") != expected_hash:
            raise RuntimeError("An existing V3.0 release differs; refusing to overwrite it.")
        if source_hash(release / "src/kde_dynamic_themes") != expected_hash:
            raise RuntimeError("Installed source files differ from the release manifest.")
    else:
        releases = release.parent
        releases.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(prefix=".kdt-staging-", dir=releases))
        try:
            shutil.copytree(pkg, temporary / "src/kde_dynamic_themes", ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
            (temporary / ".kdt-release.json").write_text(json.dumps({"version": VERSION, "sha256": expected_hash}) + "\n")
            os.replace(temporary, release)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)
    # All destination paths are validated before their final replacement.
    atomic_text(p["exe"], wrapper_text(), executable=True)
    atomic_text(p["desktop"], desktop_text(p["exe"]))
    atomic_text(p["icon"], icon.read_text(encoding="utf-8"))
    current = p["current"]
    link = current.with_name(".kdt-current-staging")
    if os.path.lexists(link):
        raise RuntimeError(f"Unexpected temporary symlink; investigate: {link}")
    try:
        link.symlink_to(release)
        os.replace(link, current)
    finally:
        if link.is_symlink():
            link.unlink()
    return {key: str(val) for key, val in p.items()}


def main() -> int:
    parser = argparse.ArgumentParser(description="Install KDE Dynamic Themes v3 without sudo")
    parser.add_argument("--dry-run", action="store_true", help="Check requirements without writing files")
    args = parser.parse_args()
    try:
        home = Path.home()
        preflight(home)
        locations = paths(home)
        if args.dry_run:
            for key in ("exe", "desktop", "icon"):
                check_existing_managed(locations[key])
            check_existing_current(locations)
            print("Preflight passed. No changes made.")
            return 0
        installed = install(ROOT, home)
        print("KDE Dynamic Themes v3.0 installed successfully.")
        print("Desktop launcher:", installed["desktop"])
        print("Executable:", installed["exe"])
        print("Run from KDE menu: KDE Dynamic Themes")
        print("Your existing project, wallpapers, backups and KDE settings were not changed by installation.")
        return 0
    except (RuntimeError, OSError, ValueError, json.JSONDecodeError) as exc:
        print("Installation stopped:", exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
