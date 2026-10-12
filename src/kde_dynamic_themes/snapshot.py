"""V1.5: snapshots with optional fallback image; never restore or apply."""
import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse, unquote

from .paths import PROJECT_ROOT, USER_CONFIG, USER_DATA
ROOT = PROJECT_ROOT
BACKUPS = ROOT / 'backups'
CONFIG = USER_CONFIG
WALLPAPER_CONFIG = 'plasma-org.kde.plasma.desktop-appletsrc'


def sha256(path):
    h = hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def wallpapers_from_config(path):
    result = {}
    section = ''
    if not path.is_file():
        return result
    for line in path.read_text(encoding='utf-8', errors='replace').splitlines():
        line = line.strip()
        if line.startswith('[') and line.endswith(']'):
            section = line[1:-1]
        m = re.fullmatch(r'Containments\]\[(\d+)\]\[Wallpaper\]\[org\.kde\.image\]\[General', section)
        if m and line.startswith('Image='):
            uri = line[6:]
            parsed = urlparse(uri)
            local = unquote(parsed.path) if parsed.scheme == 'file' and parsed.netloc in ('', 'localhost') else None
            result[m.group(1)] = {'uri': uri, 'local_path': local,
                                   'exists': bool(local and Path(local).is_file())}
    return result


