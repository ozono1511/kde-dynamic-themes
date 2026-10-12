#!/usr/bin/env python3
"""Verify the installed source and launcher's files; optional read-only KDE doctor."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
from install import VERSION, source_hash, paths, MARKER


def inspect(home: Path, *, env=None) -> list[str]:
    p = paths(home, env)
    issues = []
    release = p["release"]
    if not release.is_dir() or release.is_symlink():
        issues.append("Managed release directory missing or invalid")
    else:
        try:
            manifest = json.loads((release / ".kdt-release.json").read_text())
            if manifest.get("version") != VERSION or manifest.get("sha256") != source_hash(release / "src/kde_dynamic_themes"):
                issues.append("Code manifest mismatch")
        except (OSError, ValueError, TypeError):
            issues.append("Missing or damaged code manifest")
    if not p["current"].is_symlink() or p["current"].resolve() != release.resolve():
        issues.append("Active release symlink mismatch")
    for key in ("exe", "desktop", "icon"):
        path = p[key]
        if path.is_symlink() or not path.is_file() or MARKER not in path.read_text(encoding="utf-8"):
            issues.append(f"Launcher asset not present or unmanaged: {path}")
    return issues


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--doctor", action="store_true", help="Also run Plasma compatibility check without changes")
    args = parser.parse_args()
    problems = inspect(Path.home())
    if args.doctor and not problems:
        result = subprocess.run([str(paths(Path.home())["exe"]), "--doctor"],
                                text=True, capture_output=True, timeout=25)
        if result.returncode:
            problems.append("Host doctor failed: " + (result.stderr or result.stdout)[:500])
        else:
            try:
                data = json.loads(result.stdout)
                problems += ["Host: " + issue for issue in data.get("issues", [])]
            except ValueError:
                problems.append("Invalid host doctor output")
    if problems:
        for problem in problems:
            print("ISSUE:", problem)
        return 1
    print("KDE Dynamic Themes v3.0 installation verified. No desktop settings were modified.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
