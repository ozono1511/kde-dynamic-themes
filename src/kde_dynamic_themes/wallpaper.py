"""V1.7 wallpaper-only apply and restore. No direct editing of active KDE configs."""
import json
import shutil
import subprocess
import time
from pathlib import Path

from .snapshot import wallpapers_from_config, WALLPAPER_CONFIG
from .platform import active_targets

from .paths import PROJECT_ROOT, USER_CONFIG, USER_DATA
ROOT = PROJECT_ROOT
LIBRARY = ROOT / 'wallpapers'
ACTIVE_CONFIG = USER_CONFIG / WALLPAPER_CONFIG
APPLY_TOOL = Path(shutil.which('plasma-apply-wallpaperimage') or '/usr/bin/plasma-apply-wallpaperimage')
RECORD = ROOT / 'config' / 'wallpaper-v1.7-last.json'
def get_targets():
    """Resolve active Plasma containments at operation time, never hard-code IDs."""
    return active_targets(ACTIVE_CONFIG)


def allowed_sources():
    """Only project wallpapers and explicitly registered external folders are trusted."""
    folders = [LIBRARY]
    file = ROOT / 'config/wallpaper-sources.json'
    if file.is_file() and not file.is_symlink():
        try:
            registered = json.loads(file.read_text(encoding='utf-8'))
            if isinstance(registered, list):
                folders += [Path(x).expanduser() for x in registered if isinstance(x, str)]
        except (ValueError, OSError):
            pass
    return [x.resolve() for x in folders if x.is_dir()]



def _safe_image(path):
    p = Path(path).expanduser().resolve(strict=True)
    if not p.is_file() or p.suffix.lower() not in {'.jpg', '.jpeg', '.png', '.webp', '.bmp'}:
        raise ValueError('Select a supported image file.')
    if not any(p.is_relative_to(folder) for folder in allowed_sources()):
        raise ValueError('Wallpaper must be inside the library or a registered image folder.')
    return p


def _run(image):
    if not APPLY_TOOL.is_file():
        raise RuntimeError('plasma-apply-wallpaperimage was not found; no changes were made.')
    result = subprocess.run([str(APPLY_TOOL), str(image)], capture_output=True, text=True, timeout=25)
    if result.returncode:
        raise RuntimeError(f'Plasma reported an error: {(result.stderr or result.stdout)[:500]}')
    return result


def _matching(image):
    target = Path(image).resolve()
    current = wallpapers_from_config(ACTIVE_CONFIG)
    matches = set()
    for cid, info in current.items():
        p = info.get('local_path')
        if cid in get_targets() and p and Path(p).resolve() == target:
            matches.add(cid)
    return matches


def _verify(image):
    # Plasma may write its config asynchronously; never claim success from exit code alone.
    for _ in range(12):
        if _matching(image) == get_targets():
            return True
        time.sleep(0.35)
    return False


