#!/usr/bin/env python3
"""Remove only the v3 menu integration. Never change KDE themes or user data."""
from pathlib import Path
import sys
from install import MARKER, paths


def main() -> int:
    p = paths(Path.home())
    for key in ("exe", "desktop", "icon"):
        file = p[key]
        if file.is_symlink():
            print(f"Refusing to touch symlink: {file}", file=sys.stderr)
            return 1
        if file.exists() and (not file.is_file() or MARKER not in file.read_text(encoding="utf-8")):
            print(f"Refusing to remove non-KDT file: {file}", file=sys.stderr)
            return 1
    for key in ("exe", "desktop", "icon"):
        p[key].unlink(missing_ok=True)
    print("KDE Dynamic Themes launcher removed.")
    print("Code releases, wallpapers, colors, backups and project settings have been preserved.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
