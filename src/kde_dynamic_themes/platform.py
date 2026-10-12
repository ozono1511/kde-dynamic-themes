"""Read-only host detection and KDE Plasma 6 compatibility checks.

Distribution names are advisory: runtime capabilities and containment mapping are
what decide whether applying a wallpaper is safe. No package commands are run.
"""
from __future__ import annotations

import json
import os
import re
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path

from .paths import PROJECT_ROOT, USER_CONFIG

OS_RELEASE = Path('/etc/os-release')
WALLPAPER_CONFIG = USER_CONFIG / 'plasma-org.kde.plasma.desktop-appletsrc'
HOST_FILE = PROJECT_ROOT / 'config' / 'host.json'

TOOLS = ('plasma-apply-wallpaperimage', 'plasma-apply-colorscheme', 'kwriteconfig6', 'kreadconfig6')


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


def read_host_config(path: Path = HOST_FILE) -> dict:
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


def active_targets(path: Path = WALLPAPER_CONFIG, host: dict | None = None) -> frozenset[str]:
    settings = read_host_config() if host is None else host
    raw = path.read_text(encoding='utf-8', errors='replace')
    return resolve_containment_ids(raw, settings.get('containment_ids'), settings.get('expected_monitors', 2))


def diagnostic(project: Path = PROJECT_ROOT, config_path: Path = WALLPAPER_CONFIG, 
               os_release_path: Path = OS_RELEASE, *, command_lookup=shutil.which) -> dict:
    try:
        release = parse_os_release(os_release_path.read_text(encoding='utf-8'))
    except OSError:
        release = {}
    distro = detect_distro(release, Path('/run/ostree-booted').exists())
    checks = {name: command_lookup(name) for name in TOOLS}
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
        ids = sorted(active_targets(config_path, config), key=int)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        ids = []
        issues.append(f'Containment mapping unresolved: {exc}')
    return {
        'distro': asdict(distro), 'desktop_backend': 'plasma6',
        'commands': checks, 'containment_ids': ids, 'issues': issues,
        'read_only': True, 'tested_integration': False,
        'note': 'Host capabilities are detected; actual theme application requires desktop validation.',
    }
