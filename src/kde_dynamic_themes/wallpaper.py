"""V1.7 wallpaper operations through Plasma's scripting API, scoped to selected desktops."""
import json
import shutil
import subprocess
import time
from pathlib import Path

from .snapshot import wallpapers_from_config, WALLPAPER_CONFIG
from .platform import active_target_map, query_plasma_desktops, validate_target_map

from .paths import PROJECT_ROOT, USER_CONFIG, USER_DATA
ROOT = PROJECT_ROOT
LIBRARY = ROOT / 'wallpapers'
ACTIVE_CONFIG = USER_CONFIG / WALLPAPER_CONFIG
RECORD = ROOT / 'config' / 'wallpaper-v1.7-last.json'
def get_targets():
    """Resolve active Plasma containments at operation time, never hard-code IDs."""
    return frozenset(get_target_map())


def get_target_map():
    return active_target_map(ACTIVE_CONFIG)


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


def build_apply_script(image_uri, targets, screen_count):
    """Build a Plasma script that writes only the explicitly selected desktops."""
    entries = [{'id': str(cid), 'screen': int(screen)} for cid, screen in targets.items()]
    encoded = json.dumps(json.dumps(entries, separators=(',', ':')))
    image = json.dumps(image_uri)
    return (
        f'const expected = JSON.parse({encoded}); '
        f'const image = {image}; '
        'const current = desktops(); '
        'const selected = expected.map(e => current.find(d => String(d.id) === e.id)); '
        'const valid = selected.every((d, i) => d && Number(d.screen) === expected[i].screen '
        '&& String(d.wallpaperPlugin) === "org.kde.image"); '
        f'if (!valid || Number(screenCount) !== {int(screen_count)}) {{ '
        'print("KDT_APPLY:{\\"ok\\":false,\\"reason\\":\\"Plasma desktop mapping changed; no wallpaper was written.\\"}"); '
        '} else { '
        'selected.forEach(d => { d.wallpaperPlugin = "org.kde.image"; '
        'd.currentConfigGroup = ["Wallpaper", "org.kde.image", "General"]; '
        'd.writeConfig("Image", image); d.reloadConfig(); }); '
        'print("KDT_APPLY:" + JSON.stringify({ok:true,ids:expected.map(e => e.id)})); }'
    )


def _run(image, targets=None, *, allow_partial=False):
    if targets is None:
        targets = get_target_map()
    if not isinstance(targets, dict) or not targets:
        raise RuntimeError('No validated Plasma desktop targets; wallpaper was not changed.')
    try:
        live = validate_target_map(targets, require_full_coverage=not allow_partial)
    except ValueError as exc:
        raise RuntimeError(f'{exc} Wallpaper was not changed.') from exc
    command = shutil.which('qdbus6') or shutil.which('qdbus')
    if not command:
        raise RuntimeError('Cannot update selected Plasma desktops: qdbus6/qdbus is unavailable.')
    uri = Path(image).resolve().as_uri()
    script = build_apply_script(uri, targets, live['screen_count'])
    try:
        result = subprocess.run(
            [command, 'org.kde.plasmashell', '/PlasmaShell',
             'org.kde.PlasmaShell.evaluateScript', script],
            capture_output=True, text=True, timeout=10, check=False,
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'Could not update selected Plasma desktops: {exc}') from exc
    if result.returncode:
        raise RuntimeError(f'Plasma reported an error: {(result.stderr or result.stdout)[:500]}')
    marker = 'KDT_APPLY:'
    payloads = [line.split(marker, 1)[1].strip() for line in result.stdout.splitlines() if marker in line]
    if len(payloads) != 1:
        raise RuntimeError('Plasma did not confirm the selected desktop update; inspect the journal and wallpaper state.')
    try:
        reply = json.loads(payloads[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError('Plasma returned an invalid selected desktop update result.') from exc
    if not reply.get('ok') or set(reply.get('ids', [])) != set(targets):
        raise RuntimeError(reply.get('reason', 'Plasma did not confirm all selected desktop updates.'))
    return result


def _matching(image, targets=None):
    target = Path(image).resolve()
    current = wallpapers_from_config(ACTIVE_CONFIG)
    selected = set(targets if targets is not None else get_target_map())
    matches = set()
    for cid in selected:
        info = current.get(cid, {})
        p = info.get('local_path')
        if p and Path(p).resolve() == target:
            matches.add(cid)
    return matches


def _verify(image, targets=None):
    # Plasma may write its config asynchronously; never claim success from exit code alone.
    selected = set(targets if targets is not None else get_target_map())
    for _ in range(12):
        if _matching(image, selected) == selected:
            return True
        time.sleep(0.35)
    return False
