# KDE Dynamic Themes 3.0

A lightweight wallpaper and color gallery for **Bazzite + KDE Plasma 6**. Pick an image, preview its Matugen palette, and apply matching Plasma and Konsole colors with a single click. Includes direct theme switching and a stable recovery baseline (solid black wallpaper, Sweet-Ambar-Blue KDE scheme, Konsole Vapor).

**Status:** 3.0 desktop release package. The core application was validated on an actual dual-monitor Bazzite system in engineering 2.6.1. The v3 desktop-launcher install must still be validated on the target machine. Source is prepared for a public GitHub repository, but no repository is currently published.

## Install on Bazzite (no sudo)

Unzip the release in Downloads, then run:

```bash
cd "$HOME/Downloads/kde-dynamic-themes-v3.0.0"
python3 scripts/install.py
```

Launch it from the KDE application menu: **KDE Dynamic Themes**. You can also run `~/.local/bin/kde-dynamic-themes`. To check without changing the active theme:

```bash
python3 scripts/verify_install.py --doctor
```

The installer **does not** change your wallpaper, KDE colors, Konsole profile, old application, existing backups or library. It does not use `sudo`, RPM layering, `pip`, or a background service. It uses the already validated Python/PySide6 and `~/Projects/kde-dynamic-themes/bin/matugen`. Missing prerequisites stop installation rather than modify Bazzite.

See [installation instructions in Portuguese](docs/INSTALL_PT.md) and [dependencies](docs/DEPENDENCIES.md).

## Safety and data

- User wallpapers, Matugen binary, backups, palettes, baseline and Konsole profiles are **not included** in the release/GitHub repository.
- The application reads/writes its existing live data in `~/Projects/kde-dynamic-themes` (or `KDT_PROJECT_ROOT`). Nothing is migrated automatically.
- Installed program files: `${XDG_DATA_HOME:-~/.local/share}/kde-dynamic-themes/releases/3.0.0/` and a `current` symlink.
- Installed menu integration: `~/.local/share/applications/kde-dynamic-themes.desktop`, `~/.local/bin/kde-dynamic-themes`, and a user-local SVG icon.
- Baseline recovery changes *desktop state* only after explicit confirmation in the GUI; the installer itself is read-only with respect to desktop settings.
- A transaction journal is preserved on partial recovery failure. Do not delete backup or journal files manually to clear such a failure.

To remove only the menu launcher: `python3 scripts/uninstall.py`. See [maintenance and cleanup](docs/CLEANUP.md). The old validated application remains in the original `app/` folder as a fallback.

## Versions and support

Primary release target: **Bazzite Fedora Atomic with KDE Plasma 6 / Konsole**. Python 3.12–3.14, PySide6 6.11.x, and Matugen 4.2.x are the validated design targets; dependency requirements are declared in `pyproject.toml`. The installer intentionally reuses the already working system Python rather than automatically downloading Qt/PySide6 into an isolated environment. Recheck with `--doctor` after Bazzite upgrades.

Fedora KDE and Arch KDE are *future, untested* possibilities, not advertised as supported in V3.0.

## Developers

```bash
PYTHONPATH=src python3 -m pytest -q
PYTHONPATH=src python3 -m kde_dynamic_themes --doctor
```

GitHub Actions exercises offline tests on Python 3.12, 3.13 and 3.14; it does not simulate a real Plasma desktop. See [publishing to your GitHub account](docs/GITHUB.md) and [security](docs/SECURITY.md).

## Licensing

No open-source license has been selected yet. Until one is explicitly chosen, the repository does not grant reuse/redistribution permissions beyond applicable law. Third-party dependencies have their own licenses; **Matugen's executable and PySide6 binaries are not redistributed here**. Pick a suitable license and review dependency notices before sharing releases broadly.
