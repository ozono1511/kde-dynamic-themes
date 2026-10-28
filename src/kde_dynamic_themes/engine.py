"""V2.3: direct theme switching, immutable stable baseline, transactional recovery.
No background service; no KWin changes. The black baseline is a 1x1 solid black PNG.
"""
import json
import fcntl
from contextlib import contextmanager
import os
import shutil
import struct
import subprocess
import tempfile
import zlib
from datetime import datetime
from pathlib import Path
from .snapshot import sha256, wallpapers_from_config
from .platform import read_host_config, validate_target_map
from .wallpaper import _safe_image, _run, _verify, RECORD, ACTIVE_CONFIG, get_targets, get_target_map
from .colors import (ROOT, CONFIG, COLOR_DIR, KONSOLE_DIR, STATE, APPLY_COLORS,
    extract, kde_scheme, konsole_scheme, _config_get, _effective_scheme, _scheme_id,
    _apply_colors, _kwrite, _restore_key)

BASELINE = ROOT / 'config' / 'baseline-v2.3.json'
ACTIVE = ROOT / 'config' / 'active-v2.3.json'
JOURNAL = ROOT / 'config' / 'transaction-v2.3.json'
BLACK = ROOT / 'config' / 'baseline-black.png'
BACKUPS = ROOT / 'backups'
HOST = read_host_config()
PROFILE_NAME = HOST.get('konsole_profile') or _config_get(CONFIG / 'konsolerc', 'Desktop Entry', 'DefaultProfile')
BASELINE_KDE = HOST.get('baseline_kde_scheme', 'SweetAmbarBlue')
BASELINE_KONSOLE = HOST.get('baseline_konsole_scheme', 'Vapor')
PROFILE = KONSOLE_DIR / (PROFILE_NAME or '__missing_default_profile__.profile')

@contextmanager
def exclusive_operation():
    """Cross-process safety: never let two KDT sessions change Plasma together."""
    lock_path = ROOT / 'config/.operation.lock'
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open('a+') as handle:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError('Another KDE Dynamic Themes operation is in progress.') from exc
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def atomic_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix='.kdt-', dir=path.parent)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(value, f, indent=2, ensure_ascii=False)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

def black_png_bytes():
    # Opaque RGB pixel #000000, no dependency on Pillow or ImageMagick.
    def chunk(kind, data):
        return struct.pack('!I', len(data)) + kind + data + struct.pack('!I', zlib.crc32(kind + data) & 0xffffffff)
    return b'\x89PNG\r\n\x1a\n' + chunk(b'IHDR', struct.pack('!2I5B',1,1,8,2,0,0,0)) + chunk(b'IDAT', zlib.compress(b'\x00\x00\x00\x00')) + chunk(b'IEND', b'')

def ensure_black():
    BLACK.parent.mkdir(parents=True, exist_ok=True)
    expected = black_png_bytes()
    if BLACK.exists():
        if BLACK.is_symlink() or BLACK.read_bytes() != expected:
            raise RuntimeError('Stable black recovery image was modified; operation blocked.')
    else:
        with BLACK.open('xb') as f: f.write(expected)
    return BLACK

def load_json(path):
    if path.is_symlink(): raise RuntimeError('Symlink is not allowed for transaction record: ' + str(path))
    return json.loads(path.read_text(encoding='utf-8'))

def image_now(targets=None):
    data = wallpapers_from_config(ACTIVE_CONFIG)
    selected = targets if targets is not None else get_target_map()
    vals = [data.get(cid, {}).get('local_path') for cid in selected]
    if vals and vals[0] and all(v == vals[0] for v in vals) and Path(vals[0]).is_file(): return vals[0]
    return None

def wallpapers_now(targets):
    data = wallpapers_from_config(ACTIVE_CONFIG)
    return {cid: data[cid]['local_path'] for cid in targets
            if cid in data and data[cid].get('local_path') and Path(data[cid]['local_path']).is_file()}

def preflight(targets=None):
    if JOURNAL.exists():
        raise RuntimeError('A theme transition was interrupted. Use Settings → Restore Stable Baseline.')
    if RECORD.exists():
        raise RuntimeError('An old V1.7 wallpaper transaction record is present. Recover it before proceeding.')
    if not PROFILE.is_file() or PROFILE.is_symlink():
        raise RuntimeError('Default Konsole profile is missing or invalid.')
    if _config_get(CONFIG/'konsolerc','Desktop Entry','DefaultProfile') != PROFILE_NAME:
        raise RuntimeError('The configured Konsole profile is not the default profile.')
    selected = set(targets) if targets is not None else get_targets()
    if not selected.issubset(wallpapers_from_config(ACTIVE_CONFIG)):
        raise RuntimeError('The configured Plasma wallpaper containments were not found.')
    ensure_black()

def create_baseline(targets=None):
    """Register a fixed known-good baseline, even while a KDT theme is active.

    Existing baselines are immutable; current desktop settings are kept only
    as forensic copies, never mistaken for baseline values.
    """
    if BASELINE.exists():
        return load_json(BASELINE)
    preflight(targets)
    resolved = _scheme_id(BASELINE_KDE)
    if resolved != BASELINE_KDE:
        raise RuntimeError('Stable KDE scheme SweetAmbarBlue is unavailable.')
    if not (KONSOLE_DIR / (BASELINE_KONSOLE + '.colorscheme')).is_file():
        raise RuntimeError('Stable Konsole scheme Vapor is unavailable.')
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S-%f')
    snap = BACKUPS / ('baseline-v2.3-' + stamp)
    snap.mkdir(parents=True, exist_ok=False)
    # Captured files are diagnostic snapshots, not recovery configuration.
    for p in (CONFIG / 'kdeglobals', PROFILE, ACTIVE_CONFIG):
        if p.is_file() and not p.is_symlink():
            shutil.copy2(p, snap / p.name)
    shutil.copy2(BLACK, snap / 'baseline-black.png')
    data = {'format': 'kdt-baseline-v2.3', 'color': BASELINE_KDE,
            'color_id': BASELINE_KDE, 'local_color': BASELINE_KDE,
            'local_hash': None, 'konsole': BASELINE_KONSOLE,
            'black_sha256': sha256(BLACK), 'backup': snap.name}
    atomic_json(BASELINE, data)
    return data

def validate_baseline(b):
    if b.get('format')!='kdt-baseline-v2.3' or not isinstance(b.get('color_id'), str) or not isinstance(b.get('konsole'), str):
        raise RuntimeError('Invalid stable baseline.')
    ensure_black()
    if sha256(BLACK)!=b.get('black_sha256'): raise RuntimeError('Baseline preta corrompida.')
    if not (BACKUPS/b['backup']/'baseline-black.png').is_file(): raise RuntimeError('Backup da baseline ausente.')
    if sha256(BACKUPS/b['backup']/'baseline-black.png')!=b['black_sha256']:
        raise RuntimeError('Backup da baseline corrompido.')
    _scheme_id(b['color'])
    if not (KONSOLE_DIR/(b['konsole']+'.colorscheme')).is_file():
        raise RuntimeError('Vapor Konsole color scheme was not found.')

def current_state(targets=None):
    selected = targets if targets is not None else get_target_map()
    return {'color':_effective_scheme(),
            'local_color':_config_get(CONFIG/'kdeglobals','General','ColorScheme'),
            'local_hash':_config_get(CONFIG/'kdeglobals','General','ColorSchemeHash'),
            'konsole':_config_get(PROFILE,'Appearance','ColorScheme'),
            'image':image_now(selected), 'wallpapers':wallpapers_now(selected)}

def restore_previous(prior, targets):
    problems=[]
    try:
        _apply_colors(_scheme_id(prior['color']))
        _restore_key(CONFIG/'kdeglobals','General','ColorScheme',prior['local_color'])
        _restore_key(CONFIG/'kdeglobals','General','ColorSchemeHash',prior['local_hash'])
    except Exception as exc: problems.append('Plasma: '+str(exc))
    try:
        _restore_key(PROFILE,'Appearance','ColorScheme',prior['konsole'])
    except Exception as exc: problems.append('Konsole: '+str(exc))
    try:
        records = prior.get('wallpaper_backups')
        if isinstance(records, dict):
            for cid, record in records.items():
                backup = Path(record.get('path', ''))
                if cid not in targets or backup.is_symlink() or not backup.is_file() or sha256(backup) != record.get('sha256'):
                    problems.append(f'Wallpaper backup for containment {cid} is missing or invalid')
                    continue
                try:
                    one_target = {cid: targets[cid]}
                    _run(backup, one_target, allow_partial=True)
                    if not _verify(backup, one_target):
                        problems.append(f'Previous wallpaper not confirmed for containment {cid}')
                except Exception as exc:
                    problems.append(f'Wallpaper {cid}: {exc}')
            if set(records) != set(targets):
                problems.append('Wallpaper backup mapping does not cover all selected containments')
        else:
            # Compatibility with transaction journals created by releases before
            # per-containment backups were recorded.
            backup = prior.get('image_backup')
            if backup and Path(backup).is_file() and sha256(Path(backup)) == prior.get('image_sha256'):
                _run(backup, targets)
                if not _verify(backup, targets): problems.append('Previous wallpaper not confirmed')
            else:
                problems.append('Verified previous wallpaper backup unavailable; restore stable baseline')
    except Exception as exc: problems.append('Wallpaper: '+str(exc))
    return problems


def _apply_wallpaper_only(image, targets):
    """Apply a partial monitor choice without touching global KDE/Konsole colors."""
    if JOURNAL.exists():
        raise RuntimeError('A theme transition was interrupted. Resolve it before applying a wallpaper.')
    if RECORD.exists():
        raise RuntimeError('An old V1.7 wallpaper transaction record is present. Recover it before proceeding.')
    current = wallpapers_now(targets)
    if set(current) != set(targets):
        raise RuntimeError('Every selected monitor needs an existing local wallpaper for safe rollback.')
    stamp = datetime.now().strftime('%Y%m%d%H%M%S%f')
    BACKUPS.mkdir(parents=True, exist_ok=True)
    backups = {}
    for cid, source_name in current.items():
        source = Path(source_name)
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f'Cannot safely back up the current wallpaper for containment {cid}.')
        backup_image = BACKUPS / ('tx-wallpaper-only-' + stamp + '-' + cid + source.suffix.lower())
        with backup_image.open('xb') as dest, source.open('rb') as original:
            shutil.copyfileobj(original, dest)
        backups[cid] = {'path': str(backup_image), 'sha256': sha256(backup_image)}
    tx = {'format': 'kdt-wallpaper-only-v1', 'phase': 'prepared',
          'wallpaper_targets': targets, 'wallpaper_backups': backups, 'target': str(image)}
    atomic_json(JOURNAL, tx)
    try:
        _run(image, targets, allow_partial=True)
        if not _verify(image, targets):
            raise RuntimeError('Wallpaper could not be confirmed on all selected monitors.')
        tx['phase'] = 'applied'
        atomic_json(JOURNAL, tx)
        JOURNAL.unlink()
        return 'Wallpaper applied only to the selected monitors; global KDE and Konsole colors were unchanged.'
    except Exception as exc:
        problems = []
        for cid, record in backups.items():
            backup = Path(record['path'])
            one_target = {cid: targets[cid]}
            try:
                if backup.is_symlink() or not backup.is_file() or sha256(backup) != record['sha256']:
                    raise RuntimeError('verified wallpaper backup is missing or invalid')
                _run(backup, one_target, allow_partial=True)
                if not _verify(backup, one_target):
                    raise RuntimeError('previous wallpaper was not confirmed')
            except Exception as rollback_error:
                problems.append(f'{cid}: {rollback_error}')
        if problems:
            tx['phase'] = 'recovery-needed'
            tx['problems'] = problems
            atomic_json(JOURNAL, tx)
            raise RuntimeError(f'Wallpaper application failed: {exc}; rollback incomplete: '
                               f'{"; ".join(problems)}; journal preserved.') from exc
        JOURNAL.unlink()
        raise RuntimeError(f'Wallpaper application failed; selected monitors were restored: {exc}') from exc

def apply(image, palette, mode, targets=None, *, apply_global_theme=True):
    with exclusive_operation():
        return _apply_unlocked(image, palette, mode, targets, apply_global_theme=apply_global_theme)


def _apply_unlocked(image, palette, mode, targets=None, *, apply_global_theme=True):
    image=_safe_image(image)
    targets = get_target_map() if targets is None else dict(targets)
    validate_target_map(targets, require_full_coverage=apply_global_theme)
    if not apply_global_theme:
        return _apply_wallpaper_only(image, targets)
    preflight(targets)
    b=create_baseline(targets)
    validate_baseline(b)
    prior=current_state(targets)
    if set(prior.get('wallpapers', {})) != set(targets):
        raise RuntimeError('Every selected desktop must have an existing local wallpaper before applying; no changes were made.')
    if not prior['konsole']:
        raise RuntimeError('The current Konsole color scheme could not be identified.')
    _scheme_id(prior['color'])
    c=extract(palette,mode)
    stamp=datetime.now().strftime('%Y%m%d%H%M%S%f')
    BACKUPS.mkdir(parents=True, exist_ok=True)
    wallpaper_backups = {}
    for cid, source_name in prior['wallpapers'].items():
        source = Path(source_name)
        if source.is_symlink() or not source.is_file():
            raise RuntimeError(f'Cannot safely back up the current wallpaper for containment {cid}.')
        backup_image = BACKUPS / ('tx-previous-' + stamp + '-' + cid + source.suffix.lower())
        with backup_image.open('xb') as dest, source.open('rb') as original:
            shutil.copyfileobj(original, dest)
        wallpaper_backups[cid] = {'path': str(backup_image), 'sha256': sha256(backup_image)}
    prior['wallpaper_backups'] = wallpaper_backups
    name='KDT'+stamp
    kde=COLOR_DIR/(name+'.colors')
    konsole=KONSOLE_DIR/(name+'.colorscheme')
    if kde.exists() or konsole.exists(): raise RuntimeError('Generated theme name conflict; no changes made.')
    # Record exact pre-change state before touching active KDE files.
    tx={'format':'kdt-transaction-v2.3','prior':prior,'target':str(image),
        'wallpaper_targets':targets,
        'kde':str(kde),'konsole_file':str(konsole),'phase':'prepared'}
    atomic_json(JOURNAL,tx)
    try:
        kde.parent.mkdir(parents=True,exist_ok=True)
        konsole.parent.mkdir(parents=True,exist_ok=True)
        with kde.open('x') as f: f.write(kde_scheme(c,mode,name))
        with konsole.open('x') as f: f.write(konsole_scheme(c,name))
        _apply_colors(name)
        _kwrite(PROFILE,'Appearance','ColorScheme',name)
        if _config_get(PROFILE,'Appearance','ColorScheme')!=name:
            raise RuntimeError('Konsole profile was not updated.')
        _run(image, targets)
        if not _verify(image, targets): raise RuntimeError('Wallpaper could not be confirmed on all selected desktops.')
        tx['phase']='applied'
        atomic_json(JOURNAL,tx)
        atomic_json(ACTIVE,{'format':'kdt-active-v2.3','scheme':name,'wallpaper':str(image)})
        JOURNAL.unlink()
        # Do not remove previous generated schemes here: open Konsole windows may still use them.
        # Preserve legacy transaction record as an archive for audit, after successful migration.
        if STATE.exists():
            archive=BACKUPS/('legacy-transaction-'+stamp+'.json')
            shutil.copy2(STATE,archive)
            STATE.unlink()
        return 'Theme applied to the selected desktops; Plasma and Konsole colors updated. You can apply another theme directly.'
    except Exception as exc:
        errors=restore_previous(prior, targets)
        if errors:
            tx['phase']='recovery-needed';tx['problems']=errors
            atomic_json(JOURNAL,tx)
            raise RuntimeError('Theme application failed: '+str(exc)+'\nPartial rollback: '+'; '.join(errors)+'\nUse Restore Stable Baseline.') from exc
        JOURNAL.unlink()
        raise RuntimeError('Theme application failed; previous state restored: '+str(exc)) from exc

def recover_baseline(targets=None, *, apply_global_theme=True):
    with exclusive_operation():
        return _recover_baseline_unlocked(targets, apply_global_theme=apply_global_theme)


def _recover_baseline_unlocked(targets=None, *, apply_global_theme=True):
    targets = get_target_map() if targets is None else dict(targets)
    # Resolve and validate before baseline validation or any write, so an
    # ambiguous live topology leaves every recovery target untouched.
    validate_target_map(targets, require_full_coverage=apply_global_theme)
    if not apply_global_theme and JOURNAL.exists():
        raise RuntimeError('A pending transaction needs full baseline recovery; no partial changes were made.')
    preflight_for_recovery()
    b=load_json(BASELINE)
    validate_baseline(b)
    # Keep the journal if anything fails, so recovery can be repeated safely.
    tx={'format':'kdt-baseline-recovery-v2.3','phase':'started',
        'wallpaper_targets':targets,'global_theme':apply_global_theme}
    if not JOURNAL.exists(): atomic_json(JOURNAL,tx)
    errors=[]
    if apply_global_theme:
        try:
            _apply_colors(b['color_id'])
            _restore_key(CONFIG/'kdeglobals','General','ColorScheme',b['local_color'])
            _restore_key(CONFIG/'kdeglobals','General','ColorSchemeHash',b['local_hash'])
            if _config_get(CONFIG/'kdeglobals','General','ColorScheme') != b['local_color']:
                errors.append('Plasma: local color scheme setting did not match the baseline after restore')
            if _config_get(CONFIG/'kdeglobals','General','ColorSchemeHash') != b['local_hash']:
                errors.append('Plasma: color scheme hash did not match the baseline after restore')
            effective = _effective_scheme()
            if effective not in {b['color'], b['color_id']}:
                errors.append(f'Plasma: effective color scheme is {effective!r}, expected {b["color"]!r}')
        except Exception as exc: errors.append('Plasma: '+str(exc))
        try:
            _restore_key(PROFILE,'Appearance','ColorScheme',b['konsole'])
            if _config_get(PROFILE,'Appearance','ColorScheme') != b['konsole']:
                errors.append('Konsole: profile color scheme did not match the baseline after restore')
        except Exception as exc: errors.append('Konsole: '+str(exc))
    try:
        _run(BLACK, targets, allow_partial=not apply_global_theme)
        if not _verify(BLACK, targets): errors.append('Black wallpaper could not be confirmed on all selected desktops')
    except Exception as exc: errors.append('Wallpaper: '+str(exc))
    if errors:
        raise RuntimeError('Recovery incomplete: '+'; '.join(errors)+'; recovery journal preserved.')
    if not apply_global_theme:
        if JOURNAL.exists(): JOURNAL.unlink()
        return 'Black wallpaper restored only on the selected monitors; global KDE and Konsole colors were left unchanged.'
    if ACTIVE.exists(): ACTIVE.unlink()
    if STATE.exists():
        # Legacy pending state is no longer active, but retain an audit copy.
        archive=BACKUPS/('legacy-recovered-'+datetime.now().strftime('%Y%m%d%H%M%S%f')+'.json')
        shutil.copy2(STATE,archive);STATE.unlink()
    if JOURNAL.exists(): JOURNAL.unlink()
    return 'Stable baseline restored: black wallpaper, Sweet-Ambar-Blue and Konsole Vapor. Open a new Konsole window to verify.'

def preflight_for_recovery():
    ensure_black()
    if not BASELINE.exists():
        if JOURNAL.exists():
            raise RuntimeError('Interrupted transaction without baseline; manual inspection required.')
        create_baseline()
    if not PROFILE.is_file() or PROFILE.is_symlink(): raise RuntimeError('Default Konsole profile is missing or invalid.')
