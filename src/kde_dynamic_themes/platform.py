"""Read-only host detection and KDE Plasma 6 compatibility checks.

Distribution names are advisory: runtime capabilities and containment mapping are
what decide whether applying a wallpaper is safe. No package commands are run.
"""
from __future__ import annotations

import json
import math
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

from .paths import PROJECT_ROOT, USER_CONFIG

OS_RELEASE = Path('/etc/os-release')
WALLPAPER_CONFIG = USER_CONFIG / 'plasma-org.kde.plasma.desktop-appletsrc'
HOST_FILE = PROJECT_ROOT / 'config' / 'host.json'
PLASMA_SERVICE = 'org.kde.plasmashell'
PLASMA_PATH = '/PlasmaShell'
PLASMA_METHOD = 'org.kde.PlasmaShell.evaluateScript'

TOOLS = ('plasma-apply-colorscheme', 'kwriteconfig6', 'kreadconfig6')


@dataclass(frozen=True)
class Distro:
    name: str
    distro_id: str
    family: str
    immutable: bool
    supported_profile: bool


def parse_os_release(raw: str) -> dict[str, str]:
    values = {}
    for line in raw.splitlines():
        line = line.strip()
        if not line or line.startswith('#') or '=' not in line:
            continue
        key, val = line.split('=', 1)
        if re.fullmatch(r'[A-Z][A-Z0-9_]*', key):
            values[key] = val.strip().strip('"').strip("'")
    return values


def detect_distro(os_release: dict[str, str], ostree: bool = False) -> Distro:
    distro_id = os_release.get('ID', 'unknown').lower()
    likes = set(os_release.get('ID_LIKE', '').lower().split())
    if distro_id == 'bazzite':
        family = 'fedora-atomic'
    elif distro_id in {'fedora', 'nobara'} or 'fedora' in likes:
        family = 'fedora-atomic' if ostree else 'fedora'
    elif distro_id in {'arch', 'endeavouros', 'manjaro', 'cachyos'} or 'arch' in likes:
        family = 'arch'
    else:
        family = 'other'
    return Distro(os_release.get('PRETTY_NAME', distro_id), distro_id, family,
                  ostree, family != 'other')


def read_host_config(path: Path | None = None) -> dict:
    path = HOST_FILE if path is None else path
    if not path.exists():
        return {}
    if path.is_symlink():
        raise ValueError('Host configuration must not be a symlink.')
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('Host configuration must be a JSON object.')
    allowed = {'containment_ids', 'konsole_profile', 'baseline_kde_scheme', 'baseline_konsole_scheme', 'expected_monitors'}
    unknown = set(data) - allowed
    if unknown:
        raise ValueError(f'Unknown host settings: {sorted(unknown)}')
    if 'expected_monitors' in data and (type(data['expected_monitors']) is not int or not 1 <= data['expected_monitors'] <= 8):
        raise ValueError('expected_monitors must be an integer between 1 and 8')
    for k in ('konsole_profile', 'baseline_kde_scheme', 'baseline_konsole_scheme'):
        if k in data and (not isinstance(data[k], str) or not re.fullmatch(r'[a-zA-Z0-9_.-]{1,100}', data[k])):
            raise ValueError(f'Invalid host setting {k}')
    return data


def discover_wallpaper_ids(raw: str) -> frozenset[str]:
    """Find containments with org.kde.image wallpaper Image= entries.

    These can include inactive activities: ambiguous results must be overridden
    explicitly in config/host.json and are *never* guessed by numeric ordering.
    """
    section = ''
    found = set()
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1]
        match = re.fullmatch(r'Containments\]\[(\d+)\]\[Wallpaper\]\[org\.kde\.image\]\[General', section)
        if match and stripped.startswith('Image='):
            found.add(match.group(1))
    return frozenset(found)


def discover_wallpaper_records(raw: str) -> dict[str, dict[str, str]]:
    """Read image wallpaper and screen metadata from the saved Plasma config."""
    records: dict[str, dict[str, str]] = {}
    section = ''
    for line in raw.splitlines():
        stripped = line.strip()
        if stripped.startswith('[') and stripped.endswith(']'):
            section = stripped[1:-1]
        match = re.match(r'^Containments\]\[(\d+)(.*)$', section)
        if not match:
            continue
        cid, suffix = match.groups()
        record = records.setdefault(cid, {})
        if suffix == '':
            for key in ('screen', 'lastScreen', 'activityId', 'wallpaperplugin'):
                value = re.match(rf'^{re.escape(key)}=(.*)$', stripped)
                if value:
                    record[key] = value.group(1)
        if suffix == '][Wallpaper][org.kde.image][General' and stripped.startswith('Image='):
            record['image'] = stripped[6:]
    return {cid: item for cid, item in records.items() if item.get('image')}


def query_plasma_desktops(*, command_lookup=shutil.which,
                          run=subprocess.run, timeout: float = 5) -> dict:
    """Query Plasma's read-only scripting API for desktops and screen geometry."""
    command = command_lookup('qdbus6') or command_lookup('qdbus')
    if not command:
        raise RuntimeError('Cannot query active Plasma desktops: qdbus6/qdbus is unavailable.')
    script = ('const screenData = Array.from({length: screenCount}, (_, i) => { '
              'const g = screenGeometry(i); return {index:i, geometry:{x:Number(g.x), y:Number(g.y), '
              'width:Number(g.width), height:Number(g.height)}}; }); '
              'print("KDT_DESKTOPS:" + JSON.stringify({screenCount: screenCount, screens:screenData, '
              'desktops: desktopsForActivity(currentActivity()).map(d => ({id: String(d.id), screen: Number(d.screen), '
              'wallpaperPlugin: String(d.wallpaperPlugin)}))}));')
    try:
        result = run([command, PLASMA_SERVICE, PLASMA_PATH, PLASMA_METHOD, script],
                     capture_output=True, text=True, timeout=timeout, check=False)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f'Cannot query active Plasma desktops over the user D-Bus session: {exc}') from exc
    if result.returncode:
        message = (result.stderr or result.stdout or 'D-Bus call failed').strip()
        raise RuntimeError(f'Cannot query active Plasma desktops over the user D-Bus session: {message[:400]}')
    marker = 'KDT_DESKTOPS:'
    payloads = [line.split(marker, 1)[1].strip() for line in result.stdout.splitlines() if marker in line]
    if len(payloads) != 1:
        raise RuntimeError('Plasma returned no unique desktop inventory; confirm the mapping manually.')
    try:
        payload = json.loads(payloads[0])
    except json.JSONDecodeError as exc:
        raise RuntimeError('Plasma returned an invalid desktop inventory; confirm the mapping manually.') from exc
    count = payload.get('screenCount')
    desktops = payload.get('desktops')
    screens = payload.get('screens')
    if type(count) is not int or count < 1 or not isinstance(desktops, list) or not isinstance(screens, list):
        raise RuntimeError('Plasma returned an incomplete screen inventory; confirm the mapping manually.')
    if len(screens) != count:
        raise RuntimeError('Plasma returned an incomplete screen geometry inventory; confirm the mapping manually.')
    normalized_screens = []
    seen_screens = set()
    for item in screens:
        if not isinstance(item, dict) or type(item.get('index')) is not int:
            raise RuntimeError('Plasma returned malformed screen geometry; confirm the mapping manually.')
        index = item['index']
        geometry = item.get('geometry')
        if index in seen_screens or not isinstance(geometry, dict):
            raise RuntimeError('Plasma returned duplicate or incomplete screen geometry; confirm the mapping manually.')
        values = [geometry.get(key) for key in ('x', 'y', 'width', 'height')]
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in values) or values[2] <= 0 or values[3] <= 0:
            raise RuntimeError('Plasma returned invalid screen geometry; confirm the mapping manually.')
        seen_screens.add(index)
        normalized_screens.append({'index': index, 'geometry': dict(zip(('x', 'y', 'width', 'height'), values))})
    if seen_screens != set(range(count)):
        raise RuntimeError('Plasma screen indices are inconsistent; confirm the mapping manually.')
    normalized = []
    seen_ids = set()
    for item in desktops:
        if not isinstance(item, dict):
            raise RuntimeError('Plasma returned a malformed desktop entry; confirm the mapping manually.')
        cid, screen = item.get('id'), item.get('screen')
        plugin = item.get('wallpaperPlugin')
        if not isinstance(cid, str) or not cid.isdecimal() or cid in seen_ids or type(screen) is not int or not isinstance(plugin, str):
            raise RuntimeError('Plasma returned ambiguous desktop IDs or screen assignments; confirm the mapping manually.')
        seen_ids.add(cid)
        normalized.append({'id': cid, 'screen': screen, 'wallpaperPlugin': plugin})
    return {'screen_count': count, 'screens': normalized_screens, 'desktops': normalized}


def resolve_active_desktop_map(raw: str, live: dict, override: object = None,
                               expected_count: int | None = None) -> dict[str, int]:
    """Resolve one configured image desktop per currently active Plasma screen."""
    screen_count = live.get('screen_count')
    desktops = live.get('desktops')
    if type(screen_count) is not int or screen_count < 1 or not isinstance(desktops, list):
        raise ValueError('Plasma active screen inventory is incomplete.')
    if expected_count is not None and expected_count != screen_count:
        raise ValueError(f'host.json expects {expected_count} monitors but Plasma reports {screen_count}; confirm the current desktop mapping.')
    records = discover_wallpaper_records(raw)
    active = [item for item in desktops if 0 <= item.get('screen', -1) < screen_count]
    screen_ids: dict[int, list[str]] = {}
    for item in active:
        if item.get('wallpaperPlugin') != 'org.kde.image':
            continue
        cid = item['id']
        if cid in records:
            screen_ids.setdefault(item['screen'], []).append(cid)
    if set(screen_ids) != set(range(screen_count)):
        raise ValueError(f'Plasma desktop mapping is incomplete: active screens are {list(range(screen_count))}, image desktops were found on {sorted(screen_ids)}.')
    if any(len(ids) > 1 for ids in screen_ids.values()) and override is None:
        detail = ', '.join(f'screen {screen}: {sorted(ids)}' for screen, ids in sorted(screen_ids.items()))
        raise ValueError(f'Plasma has multiple eligible desktops on the same active screen ({detail}); confirm which IDs to use.')
    automatic = {ids[0]: screen for screen, ids in screen_ids.items() if len(ids) == 1}
    if override is None:
        if len(automatic) != screen_count:
            raise ValueError('Plasma active desktop mapping is ambiguous; confirm the IDs for each active screen.')
        return automatic
    if (not isinstance(override, list) or any(not isinstance(cid, str) or not cid.isdecimal() for cid in override)
            or len(override) != len(set(override))):
        raise ValueError('host.json containment_ids must contain unique decimal-string IDs.')
    chosen = set(override)
    if not chosen.issubset(records):
        raise ValueError('Configured containment_ids are absent from Plasma image wallpaper configuration.')
    candidates = {item['id']: item['screen'] for item in active
                  if item.get('wallpaperPlugin') == 'org.kde.image' and item['id'] in records}
    selected = {cid: candidates[cid] for cid in chosen if cid in candidates}
    if len(selected) != screen_count or set(selected.values()) != set(range(screen_count)):
        raise ValueError('Configured containment_ids do not identify exactly one active image desktop on every current screen; confirm the mapping in Settings.')
    return selected


def resolve_containment_ids(raw: str, override: object = None, expected_count: int = 2) -> frozenset[str]:
    """Fail closed unless exactly the expected number of containments is known."""
    present = discover_wallpaper_ids(raw)
    if override is not None:
        if not isinstance(override, list) or len(override) != expected_count or any(
            not isinstance(x, str) or not x.isdecimal() for x in override
        ) or len(set(override)) != expected_count:
            raise ValueError('containment_ids must list unique decimal-string IDs for the active desktops.')
        selected = frozenset(override)
        if not selected.issubset(present):
            raise ValueError('Configured containment_ids are absent from Plasma config.')
        return selected
    if len(present) != expected_count:
        raise ValueError(f'Expected exactly {expected_count} wallpaper containments, found {len(present)}: {sorted(present)}. Configure host.json after identifying active desktops.')
    return present


def active_target_map(path: Path = WALLPAPER_CONFIG, host: dict | None = None,
                      live: dict | None = None) -> dict[str, int]:
    settings = read_host_config() if host is None else host
    raw = path.read_text(encoding='utf-8', errors='replace')
    inventory = query_plasma_desktops() if live is None else live
    return resolve_active_desktop_map(raw, inventory, settings.get('containment_ids'), settings.get('expected_monitors'))


def active_targets(path: Path = WALLPAPER_CONFIG, host: dict | None = None,
                   live: dict | None = None) -> frozenset[str]:
    return frozenset(active_target_map(path, host, live))


def validate_target_map(targets: dict[str, int], live: dict | None = None,
                        *, require_full_coverage: bool = True) -> dict:
    """Validate a confirmed selection against the current Plasma screen inventory."""
    if (not isinstance(targets, dict) or not targets
            or any(not isinstance(cid, str) or not cid.isdecimal() or type(screen) is not int
                   for cid, screen in targets.items())):
        raise ValueError('The selected desktop mapping is empty or malformed.')
    inventory = query_plasma_desktops() if live is None else live
    by_id = {item['id']: item for item in inventory.get('desktops', [])}
    missing = [cid for cid, screen in targets.items()
               if cid not in by_id or by_id[cid].get('screen') != screen
               or by_id[cid].get('wallpaperPlugin') != 'org.kde.image']
    if missing:
        raise ValueError(f'Selected desktops are no longer active image desktops: {sorted(missing)}. Confirm the mapping again.')
    screen_count = inventory.get('screen_count')
    if type(screen_count) is not int or screen_count < 1:
        raise ValueError('Plasma active screen inventory is incomplete; confirm the mapping again.')
    screens = [screen for screen in targets.values()]
    if any(screen < 0 or screen >= screen_count for screen in screens) or len(screens) != len(set(screens)):
        raise ValueError('Each selected containment must map to a different active physical screen.')
    covered = {screen for screen in targets.values() if 0 <= screen < screen_count}
    if require_full_coverage and covered != set(range(screen_count)):
        raise ValueError('The selected desktop mapping no longer covers every active screen. Confirm the mapping again.')
    return inventory


def physical_monitor_records(targets: dict[str, int], live: dict, outputs: list[dict]) -> list[dict]:
    """Join Plasma desktop IDs with Qt physical outputs by exact screen geometry."""
    validate_target_map(targets, live)
    if len(outputs) != live['screen_count']:
        raise ValueError('KDE and the application report different monitor counts; no safe mapping is available.')
    geometries = {item['index']: item['geometry'] for item in live.get('screens', [])}
    if set(geometries) != set(range(live['screen_count'])):
        raise ValueError('Plasma did not provide complete geometry for every monitor.')
    output_geometries = []
    for output in outputs:
        geometry = output.get('geometry')
        if not isinstance(geometry, dict):
            raise ValueError('The application could not read a physical monitor geometry.')
        values = tuple(geometry.get(key) for key in ('x', 'y', 'width', 'height'))
        if any(isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
               for value in values) or values[2] <= 0 or values[3] <= 0:
            raise ValueError('The application returned incomplete physical monitor geometry.')
        output_geometries.append(values)
    if len(set(output_geometries)) != len(output_geometries):
        raise ValueError('Physical monitors have indistinguishable geometry; no safe mapping is available.')
    records = []
    used_outputs = set()
    for cid, screen in targets.items():
        geometry = geometries[screen]
        expected = tuple(geometry[key] for key in ('x', 'y', 'width', 'height'))
        matches = [i for i, candidate in enumerate(output_geometries) if candidate == expected]
        if len(matches) != 1 or matches[0] in used_outputs:
            raise ValueError(f'Plasma screen {screen} cannot be matched uniquely to a physical monitor.')
        index = matches[0]
        used_outputs.add(index)
        output = outputs[index]
        records.append({
            'containment_id': cid,
            'screen': screen,
            'name': output.get('name'),
            'manufacturer': output.get('manufacturer'),
            'model': output.get('model'),
            'serial_number': output.get('serial_number'),
            'geometry': dict(zip(('x', 'y', 'width', 'height'), expected)),
            'pixel_size': output.get('pixel_size'),
            'refresh_rate': output.get('refresh_rate'),
        })
    return sorted(records, key=lambda record: record['screen'])


def selected_monitor_targets(monitors: list[dict], selected_ids: list[str]) -> dict[str, int]:
    """Validate a non-empty explicit checkbox selection and return ID-to-screen targets."""
    if not monitors:
        raise ValueError('Plasma did not identify any physical monitors with a trusted desktop mapping.')
    by_id = {item.get('containment_id'): item for item in monitors}
    if len(by_id) != len(monitors) or any(not isinstance(cid, str) or not cid.isdecimal() for cid in by_id):
        raise ValueError('The monitor list contains invalid or duplicate containment IDs.')
    screens = [item.get('screen') for item in monitors]
    if any(type(screen) is not int or screen < 0 for screen in screens) or len(screens) != len(set(screens)):
        raise ValueError('The monitor list contains an invalid or duplicate physical screen assignment.')
    if not isinstance(selected_ids, list) or not selected_ids:
        raise ValueError('Select at least one monitor before confirming.')
    if any(not isinstance(cid, str) or not cid.isdecimal() for cid in selected_ids):
        raise ValueError('The selection contains an invalid containment ID.')
    if len(selected_ids) != len(set(selected_ids)):
        raise ValueError('The selection contains duplicate containment IDs.')
    if not set(selected_ids).issubset(by_id):
        raise ValueError('The selection contains a monitor that is not in the current Plasma inventory.')
    return {cid: by_id[cid]['screen'] for cid in selected_ids}


def eligible_target_options(raw: str, live: dict) -> list[dict]:
    """List saved image containments with live screen data for explicit UI choice."""
    live_by_id = {item['id']: item for item in live.get('desktops', [])}
    records = discover_wallpaper_records(raw)
    result = []
    for cid, record in records.items():
        current = live_by_id.get(cid)
        result.append({
            'id': cid,
            'screen': current['screen'] if current else -1,
            'wallpaperPlugin': current['wallpaperPlugin'] if current else 'unknown',
            'lastScreen': record.get('lastScreen', 'unknown'),
            'activityId': record.get('activityId', ''),
            'active': bool(current and 0 <= current['screen'] < live.get('screen_count', 0)),
            'eligible': bool(current and current['wallpaperPlugin'] == 'org.kde.image'),
        })
    return result


def save_containment_ids(ids: list[str], *, expected_monitors: int | None = None) -> Path:
    """Persist a user-confirmed mapping, backing up the prior host file first."""
    if not isinstance(ids, list) or not ids or any(not isinstance(cid, str) or not cid.isdecimal() for cid in ids):
        raise ValueError('Select one or more decimal-string containment IDs.')
    if len(ids) != len(set(ids)):
        raise ValueError('The selected containment IDs must be unique.')
    settings = read_host_config()
    settings['containment_ids'] = ids
    if 'expected_monitors' in settings and expected_monitors is not None:
        settings['expected_monitors'] = expected_monitors
    HOST_FILE.parent.mkdir(parents=True, exist_ok=True)
    backup_dir = PROJECT_ROOT / 'backups'
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    backup = backup_dir / f'host-json-prechange-{stamp}.json'
    existed = HOST_FILE.exists()
    if HOST_FILE.is_symlink():
        raise ValueError('Host configuration must not be a symlink.')
    backup_data = {'format': 'kdt-host-config-prechange-v1', 'target': str(HOST_FILE),
                   'existed_before': existed, 'recorded_at': datetime.now().astimezone().isoformat()}
    if existed:
        backup_data['previous'] = json.loads(HOST_FILE.read_text(encoding='utf-8'))
    fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w', encoding='utf-8') as handle:
        json.dump(backup_data, handle, indent=2, ensure_ascii=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())
    fd, temporary = tempfile.mkstemp(prefix='.host-', dir=HOST_FILE.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(settings, handle, indent=2, ensure_ascii=False)
            handle.write('\n')
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, HOST_FILE)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return backup


def diagnostic(project: Path = PROJECT_ROOT, config_path: Path = WALLPAPER_CONFIG, 
               os_release_path: Path = OS_RELEASE, *, command_lookup=shutil.which,
               desktop_provider=query_plasma_desktops) -> dict:
    try:
        release = parse_os_release(os_release_path.read_text(encoding='utf-8'))
    except OSError:
        release = {}
    distro = detect_distro(release, Path('/run/ostree-booted').exists())
    checks = {name: command_lookup(name) for name in TOOLS}
    checks['plasma_dbus'] = command_lookup('qdbus6') or command_lookup('qdbus')
    matugen = project / 'bin' / 'matugen'
    checks['matugen'] = str(matugen) if matugen.is_file() and os.access(matugen, os.X_OK) else command_lookup('matugen')
    issues = []
    if not distro.supported_profile:
        issues.append('Distribution not profiled; manual compatibility validation required.')
    for name, location in checks.items():
        if not location:
            issues.append(f'Missing command: {name}')
    try:
        config = read_host_config(project / 'config' / 'host.json')
        ids = sorted(active_targets(config_path, config, desktop_provider()), key=int)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        ids = []
        issues.append(f'Containment mapping unresolved: {exc}')
    return {
        'distro': asdict(distro), 'desktop_backend': 'plasma6',
        'commands': checks, 'containment_ids': ids, 'issues': issues,
        'read_only': True, 'tested_integration': False,
        'note': 'Host capabilities are detected; actual theme application requires desktop validation.',
    }
