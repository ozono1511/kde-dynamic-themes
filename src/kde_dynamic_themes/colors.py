"""V2.0.3 controlled theme transaction; edit only Konsole Appearance/ColorScheme with snapshot."""
import configparser
import re
import shutil
import subprocess
from pathlib import Path

from .paths import PROJECT_ROOT, USER_CONFIG, USER_DATA
ROOT = PROJECT_ROOT
CONFIG = USER_CONFIG
COLOR_DIR = USER_DATA / 'color-schemes'
KONSOLE_DIR = USER_DATA / 'konsole'
STATE = ROOT / 'config' / 'theme-v2.0-pending.json'
APPLY_COLORS = shutil.which('plasma-apply-colorscheme')
HEX = re.compile(r'^#[0-9a-fA-F]{6}$')

def rgb(value):
    if not isinstance(value, str) or not HEX.fullmatch(value):
        raise ValueError('Invalid Matugen palette: hexadecimal color expected.')
    return ','.join(str(int(value[i:i+2], 16)) for i in (1, 3, 5))

def extract(palette, mode):
    if mode not in ('dark', 'light'):
        raise ValueError('Invalid color mode')
    colors = palette['colors']
    def get(key):
        return rgb(colors[key][mode]['color'])
    keys = ('background', 'on_background', 'surface', 'on_surface', 'surface_container',
            'surface_container_high', 'primary', 'on_primary', 'secondary', 'tertiary',
            'outline', 'error')
    return {key: get(key) for key in keys}

def kde_scheme(c, mode, name):
    dark = mode == 'dark'
    return f'''[General]
Name={name}
ColorScheme={name}
shadeSortColumn=true

[ColorEffects:Disabled]
Color=128,128,128
ColorAmount=0
ColorEffect=0
ContrastAmount=0.65
ContrastEffect=1
IntensityAmount=0.1
IntensityEffect=2

[Colors:Window]
BackgroundNormal={c['surface']}
ForegroundNormal={c['on_surface']}
BackgroundAlternate={c['surface_container']}
ForegroundInactive={c['outline']}
ForegroundActive={c['primary']}
ForegroundLink={c['primary']}
ForegroundVisited={c['tertiary']}
ForegroundNegative={c['error']}
ForegroundNeutral={c['secondary']}
ForegroundPositive={c['primary']}
ForegroundPlaceholder={c['outline']}
DecorationFocus={c['primary']}
DecorationHover={c['secondary']}

[Colors:View]
BackgroundNormal={c['background']}
BackgroundAlternate={c['surface_container']}
ForegroundNormal={c['on_surface']}
ForegroundInactive={c['outline']}
ForegroundActive={c['primary']}
ForegroundLink={c['primary']}
ForegroundVisited={c['tertiary']}
ForegroundNegative={c['error']}
ForegroundNeutral={c['secondary']}
ForegroundPositive={c['primary']}
ForegroundPlaceholder={c['outline']}
DecorationFocus={c['primary']}
DecorationHover={c['secondary']}

[Colors:Button]
BackgroundNormal={c['surface_container']}
BackgroundAlternate={c['surface_container_high']}
ForegroundNormal={c['on_surface']}
ForegroundInactive={c['outline']}
ForegroundActive={c['primary']}
ForegroundLink={c['primary']}
ForegroundVisited={c['tertiary']}
ForegroundNegative={c['error']}
ForegroundNeutral={c['secondary']}
ForegroundPositive={c['primary']}
ForegroundPlaceholder={c['outline']}
DecorationFocus={c['primary']}
DecorationHover={c['secondary']}

[Colors:Selection]
BackgroundNormal={c['primary']}
BackgroundAlternate={c['primary']}
ForegroundNormal={c['on_primary']}
ForegroundInactive={c['on_primary']}
ForegroundActive={c['on_primary']}
ForegroundLink={c['on_primary']}
ForegroundVisited={c['on_primary']}
ForegroundNegative={c['on_primary']}
ForegroundNeutral={c['on_primary']}
ForegroundPositive={c['on_primary']}
ForegroundPlaceholder={c['on_primary']}
DecorationFocus={c['primary']}
DecorationHover={c['secondary']}

[Colors:Tooltip]
BackgroundNormal={c['surface_container_high']}
BackgroundAlternate={c['surface_container']}
ForegroundNormal={c['on_surface']}
ForegroundInactive={c['outline']}
ForegroundActive={c['primary']}
ForegroundLink={c['primary']}
ForegroundVisited={c['tertiary']}
ForegroundNegative={c['error']}
ForegroundNeutral={c['secondary']}
ForegroundPositive={c['primary']}
ForegroundPlaceholder={c['outline']}
DecorationFocus={c['primary']}
DecorationHover={c['secondary']}

[WM]
activeBackground={c['surface']}
activeForeground={c['on_surface']}
inactiveBackground={c['surface_container']}
inactiveForeground={c['outline']}
activeBlend={c['surface']}
inactiveBlend={c['surface_container']}

[KDE]
contrast=4

[ColorEffects:Inactive]
Enable=false
'''

def konsole_scheme(c, name):
    # Use the same color for every ANSI slot initially; user can refine later.
    colors = [c['background'], c['error'], c['primary'], c['secondary'], c['primary'],
              c['tertiary'], c['secondary'], c['on_surface']]
    bright = [c['surface_container_high'], c['error'], c['primary'], c['secondary'],
              c['primary'], c['tertiary'], c['secondary'], c['on_surface']]
    lines = ['[General]', f'Description={name}', 'Opacity=1', '', '[Background]', f'Color={c["background"]}', '',
             '[Foreground]', f'Color={c["on_surface"]}', '']
    for i, value in enumerate(colors + bright):
        lines.extend([f'[Color{i}]', f'Color={value}', ''])
    return '\n'.join(lines)

def _exec(args):
    result = subprocess.run(args, capture_output=True, text=True, timeout=30)
    if result.returncode:
        raise RuntimeError(f'{Path(args[0]).name}: {(result.stderr or result.stdout)[:400]}')

def _config_get(path, section, key):
    parser = configparser.RawConfigParser(interpolation=None, strict=False)
    parser.optionxform = str
    if path.exists():
        parser.read(path, encoding='utf-8')
    return parser.get(section, key, fallback=None)

def _kwrite(path, group, key, value):
    tool = shutil.which('kwriteconfig6')
    if not tool:
        raise RuntimeError('kwriteconfig6 was not found.')
    _exec([tool, '--file', str(path), '--group', group, '--key', key, value])

def _restore_key(path, group, key, previous):
    if previous is None:
        tool = shutil.which('kwriteconfig6')
        if not tool:
            raise RuntimeError('kwriteconfig6 was not found; unable to remove configuration key.')
        _exec([tool, '--file', str(path), '--group', group, '--key', key, '--delete'])
    else:
        _kwrite(path, group, key, previous)

def _apply_colors(name):
    if not APPLY_COLORS:
        raise RuntimeError('plasma-apply-colorscheme was not found.')
    _exec([APPLY_COLORS, name])

def _scheme_id(name):
    """Resolve a configured KDE scheme to an installed CLI scheme, without guessing."""
    if not name or not APPLY_COLORS:
        raise RuntimeError('Previous color scheme is missing or KDE tool is unavailable.')
    result = subprocess.run([APPLY_COLORS, '-l'], capture_output=True, text=True, timeout=15)
    if result.returncode:
        raise RuntimeError('Unable to list available KDE color schemes.')
    # Plasma appends ' (current color scheme)' to the active entry.
    # This annotation is display metadata, not part of the scheme ID.
    available = [re.sub(r'\s+\(current color scheme\)\s*$', '', line.strip()[2:].strip(), flags=re.I)
                 for line in result.stdout.splitlines() if line.strip().startswith('* ')]
    if name in available:
        return name
    normalized = lambda x: re.sub(r'[^a-z0-9]', '', x.casefold())
    candidates = [item for item in available if normalized(item) == normalized(name)]
    if len(candidates) != 1:
        raise RuntimeError('Unable to uniquely resolve the previous scheme '
                           + repr(name) + '. Available: ' + ', '.join(available))
    candidate = candidates[0]
    # Verify actual installed .colors file matches the CLI name, not just the text.
    dirs = [COLOR_DIR, Path('/usr/share/color-schemes'), Path('/usr/local/share/color-schemes')]
    if not any((directory / (candidate + '.colors')).is_file() for directory in dirs):
        raise RuntimeError('Equivalent color scheme found but its .colors file is missing: ' + candidate)
    return candidate

def _effective_scheme():
    tool = shutil.which('kreadconfig6')
    if not tool:
        raise RuntimeError('kreadconfig6 was not found.')
    result = subprocess.run([tool, '--file', 'kdeglobals', '--group', 'General', '--key', 'ColorScheme'],
                            capture_output=True, text=True, timeout=15)
    if result.returncode or not result.stdout.strip():
        raise RuntimeError('Unable to identify the effective KDE color scheme. Application blocked.')
    return result.stdout.strip()


