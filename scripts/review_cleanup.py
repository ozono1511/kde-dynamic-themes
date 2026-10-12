#!/usr/bin/env python3
"""Read-only engineering inventory. Does not rename, copy, or delete any files.

Conservative by design: 'candidate' never means 'safe to delete'. It means
an engineer must check external launchers, runtime references, and recovery state.
"""
import argparse
import ast
import json
import os
from pathlib import Path

MODULES = ("__main__", "ui", "engine", "colors", "wallpaper", "snapshot", "platform", "paths")
PROTECTED = {"backups", "wallpapers", "bin", "presets", "config", "palettes", "logs"}


def source_imports(package: Path) -> dict[str, list[str]]:
    """Parse only AST; does not import or execute application modules."""
    available = {f.stem for f in package.glob("*.py") if f.is_file()}
    refs = {}
    for file in sorted(package.glob("*.py")):
        refs[file.stem] = []
        tree = ast.parse(file.read_text(encoding="utf-8"), filename=str(file))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
                member = node.module.split(".", 1)[0]
                if member in available:
                    refs[file.stem].append(member)
            elif isinstance(node, ast.ImportFrom) and node.level == 1 and node.module is None:
                for alias in node.names:
                    if alias.name in available:
                        refs[file.stem].append(alias.name)
    return {k: sorted(set(v)) for k, v in refs.items()}


def reachable(graph: dict[str, list[str]], entry: str = "__main__") -> list[str]:
    found, pending = set(), [entry]
    while pending:
        name = pending.pop()
        if name not in graph or name in found:
            continue
        found.add(name)
        pending.extend(graph[name])
    return sorted(found)


def inventory(project: Path, source_package: Path, home: Path | None = None) -> dict:
    home = home or Path.home()
    report = {"read_only": True, "project": str(project), "active_source_imports": {},
              "active_source_modules": [], "unreferenced_source_modules": [],
              "historical_gallery_candidates": [], "legacy_engine_candidates": [],
              "bytecode_candidates": [], "generated_schemes_protected": [],
              "protected_directories": sorted(PROTECTED), "warnings": []}
    if source_package.is_dir():
        try:
            imports = source_imports(source_package)
            used = reachable(imports)
            report["active_source_imports"] = imports
            report["active_source_modules"] = used
            report["unreferenced_source_modules"] = sorted(set(imports) - set(used) - {"__init__"})
        except (OSError, SyntaxError, UnicodeError) as exc:
            report["warnings"].append(f"Unable to parse Python module graph: {exc}")
    else:
        report["warnings"].append("Source package missing: dependency graph not checked")
    app = project / "app"
    if app.is_dir():
        # Explicitly protect the locally validated fallbacks; no automatic deletion.
        protected_gallery = {"gallery_v2_5.py", "gallery_v2_6.py"}
        for file in sorted(app.glob("gallery_v*.py")):
            if file.is_symlink() or not file.is_file() or file.name in protected_gallery:
                continue
            report["historical_gallery_candidates"].append(str(file))
        live_engines = {"theme_v2_3.py", "theme_v2_0_3.py", "snapshot_v1_5.py", "wallpaper_v1_7.py"}
        for pattern in ("theme_v*.py", "restore_v*.py", "snapshot_v*.py", "wallpaper_v*.py"):
            for file in sorted(app.glob(pattern)):
                if file.is_symlink() or not file.is_file() or file.name in live_engines:
                    continue
                report["legacy_engine_candidates"].append(str(file))
    if project.is_dir():
        for dirpath, dirname, filenames in os.walk(project, followlinks=False):
            dirname[:] = [d for d in dirname if not (Path(dirpath)/d).is_symlink()]
            for filename in filenames:
                file = Path(dirpath)/filename
                if filename.endswith('.pyc') and file.is_file() and not file.is_symlink():
                    report["bytecode_candidates"].append(str(file))
    for folder, suffix in ((home/".local/share/color-schemes", ".colors"),
                           (home/".local/share/konsole", ".colorscheme")):
        if folder.is_dir():
            for file in folder.glob("KDT*" + suffix):
                if file.is_file() and not file.is_symlink():
                    report["generated_schemes_protected"].append(str(file))
    for key in ("historical_gallery_candidates", "legacy_engine_candidates", "bytecode_candidates", "generated_schemes_protected"):
        report[key].sort()
    report["warnings"].extend([
        "Candidate lists are NOT authorization to delete. Check external launchers and runtime references.",
        "Keep all data under protected directories, and all KDT schemes, until explicit approval.",
        "Retain validated legacy engine modules until V3.0 installation and rollback are certified.",
        "The AST import graph cannot detect every dynamic import or external script reference.",
    ])
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only engineering cleanup and import inventory")
    parser.add_argument("--project", type=Path, default=Path.home()/"Projects/kde-dynamic-themes")
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[1]/"src/kde_dynamic_themes")
    parser.add_argument("--output", type=Path, help="Optional JSON report file; default prints to stdout")
    args = parser.parse_args()
    results = inventory(args.project, args.source)
    serialized = json.dumps(results, indent=2, ensure_ascii=False) + "\n"
    if args.output:
        # This writes only the requested report, never mutates the project files.
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(serialized, encoding="utf-8")
        print("Report written to:", args.output)
    else:
        print(serialized, end="")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
