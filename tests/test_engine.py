import json
from pathlib import Path

import pytest

from kde_dynamic_themes import colors, engine, wallpaper


def test_registered_external_wallpapers(tmp_path, monkeypatch):
    library = tmp_path/'wallpapers'
    external = tmp_path/'external'
    other = tmp_path/'other'
    for directory in (library, external, other):
        directory.mkdir()
        (directory/'sample.png').write_bytes(b'PNG fake for safe-path tests')
    (tmp_path/'config').mkdir()
    (tmp_path/'config/wallpaper-sources.json').write_text(json.dumps([str(external)]))
    monkeypatch.setattr(wallpaper, 'ROOT', tmp_path)
    monkeypatch.setattr(wallpaper, 'LIBRARY', library)
    assert wallpaper._safe_image(library/'sample.png') == library/'sample.png'
    assert wallpaper._safe_image(external/'sample.png') == external/'sample.png'
    with pytest.raises(ValueError, match='registered image folder'):
        wallpaper._safe_image(other/'sample.png')


def test_theme_palette_schema_validation():
    colors_in = {k: {'dark': {'color': '#1299AA'}} for k in (
        'background','on_background','surface','on_surface','surface_container',
        'surface_container_high','primary','on_primary','secondary','tertiary','outline','error')}
    assert colors.extract({'colors': colors_in}, 'dark')['primary'] == '18,153,170'
    colors_in['primary']['dark']['color'] = 'not-a-color'
    with pytest.raises(ValueError):
        colors.extract({'colors': colors_in}, 'dark')


def test_partial_apply_keeps_verified_wallpaper_backup(tmp_path, monkeypatch):
    old = tmp_path/'old.png'
    old.write_bytes(b'old image, must survive the failed attempt')
    new = tmp_path/'new.png'
    new.write_bytes(b'new image')
    for folder in ('config','backup','kde','konsole'):
        (tmp_path/folder).mkdir()
    monkeypatch.setattr(engine, 'ROOT', tmp_path)
    monkeypatch.setattr(engine, 'JOURNAL', tmp_path/'config/transaction.json')
    monkeypatch.setattr(engine, 'BACKUPS', tmp_path/'backup')
    monkeypatch.setattr(engine, 'COLOR_DIR', tmp_path/'kde')
    monkeypatch.setattr(engine, 'KONSOLE_DIR', tmp_path/'konsole')
    monkeypatch.setattr(engine, 'STATE', tmp_path/'no-legacy-state')
    monkeypatch.setattr(engine, 'get_target_map', lambda: {'94': 0, '95': 1})
    monkeypatch.setattr(engine, 'validate_target_map', lambda targets, **_kw: {'screen_count': 2, 'desktops': []})
    monkeypatch.setattr(engine, '_safe_image', lambda path: Path(path))
    monkeypatch.setattr(engine, 'preflight', lambda *args: None)
    monkeypatch.setattr(engine, 'create_baseline', lambda *args: {})
    monkeypatch.setattr(engine, 'validate_baseline', lambda b: None)
    monkeypatch.setattr(engine, 'current_state', lambda *args: {
        'image': str(old), 'konsole': 'Vapor', 'color': 'SweetAmbarBlue',
        'local_color': 'SweetAmbarBlue', 'local_hash': None,
        'wallpapers': {'94': str(old), '95': str(old)},
    })
    monkeypatch.setattr(engine, '_scheme_id', lambda x: x)
    monkeypatch.setattr(engine, 'extract', lambda palette, mode: {'primary': '1,2,3'})
    monkeypatch.setattr(engine, 'kde_scheme', lambda *args: 'KDE colors\n')
    monkeypatch.setattr(engine, 'konsole_scheme', lambda *args: 'Konsole colors\n')
    def fail_apply(*args):
        raise RuntimeError('fake Plasma apply failure')
    monkeypatch.setattr(engine, '_apply_colors', fail_apply)
    verified = []
    def pretend_recovered(prior, targets):
        backups = prior['wallpaper_backups']
        assert set(backups) == set(targets)
        for item in backups.values():
            b = Path(item['path'])
            assert b.read_bytes() == old.read_bytes()
            assert item['sha256'] == engine.sha256(b)
        verified.append(True)
        return []
    monkeypatch.setattr(engine, 'restore_previous', pretend_recovered)
    with pytest.raises(RuntimeError, match='Theme application failed'):
        engine.apply(new, {}, 'dark')
    assert verified
    assert not (tmp_path/'config/transaction.json').exists()
    assert len(list((tmp_path/'backup').glob('tx-previous-*'))) == 2
    assert old.read_bytes() == b'old image, must survive the failed attempt'


def test_recovery_mapping_failure_preserves_journal_before_any_change(tmp_path, monkeypatch):
    journal = tmp_path/'transaction.json'
    journal.write_text('{"phase":"recovery-needed"}')
    calls = []
    monkeypatch.setattr(engine, 'JOURNAL', journal)
    monkeypatch.setattr(engine, 'get_target_map', lambda: {'239': -1})
    def reject_mapping(targets, **_kw):
        raise ValueError('mapping is ambiguous')
    monkeypatch.setattr(engine, 'validate_target_map', reject_mapping)
    monkeypatch.setattr(engine, 'preflight_for_recovery', lambda: calls.append('preflight'))
    monkeypatch.setattr(engine, '_apply_colors', lambda *_: calls.append('colors'))
    with pytest.raises(ValueError, match='mapping is ambiguous'):
        engine._recover_baseline_unlocked()
    assert calls == []
    assert journal.read_text() == '{"phase":"recovery-needed"}'


def test_partial_monitor_theme_changes_only_selected_wallpaper(tmp_path, monkeypatch):
    from kde_dynamic_themes import engine

    old94 = tmp_path/'old-94.png'
    old95 = tmp_path/'old-95.png'
    old239 = tmp_path/'old-239.png'
    new = tmp_path/'new.png'
    for path in (old94, old95, old239, new):
        path.write_bytes(path.name.encode())
    state = {'94': str(old94), '95': str(old95), '239': str(old239)}
    monkeypatch.setattr(engine, 'JOURNAL', tmp_path/'config/transaction.json')
    monkeypatch.setattr(engine, 'RECORD', tmp_path/'config/legacy.json')
    monkeypatch.setattr(engine, 'BACKUPS', tmp_path/'backups')
    monkeypatch.setattr(engine, '_safe_image', lambda path: Path(path))
    monkeypatch.setattr(engine, 'validate_target_map', lambda _targets, **_kw: {'screen_count': 2, 'desktops': []})
    monkeypatch.setattr(engine, 'wallpapers_now', lambda targets: {cid: state[cid] for cid in targets})
    monkeypatch.setattr(engine, '_run', lambda image, targets, **_kw: state.update(
        {cid: str(image) for cid in targets}))
    monkeypatch.setattr(engine, '_verify', lambda image, targets: all(
        Path(state[cid]).resolve() == Path(image).resolve() for cid in targets))
    global_calls = []
    monkeypatch.setattr(engine, '_apply_colors', lambda *_args: global_calls.append('colors'))

    result = engine._apply_unlocked(new, {}, 'dark', {'94': 0}, apply_global_theme=False)

    assert 'only to the selected monitors' in result
    assert Path(state['94']) == new
    assert state['95'] == str(old95)
    assert state['239'] == str(old239)
    assert global_calls == []
    assert not engine.JOURNAL.exists()
    assert len(list((tmp_path/'backups').glob('tx-wallpaper-only-*'))) == 1


def test_partial_rollback_restores_each_monitor_wallpaper_independently(tmp_path, monkeypatch):
    first = tmp_path/'first.png'
    second = tmp_path/'second.png'
    first.write_bytes(b'wallpaper for screen zero')
    second.write_bytes(b'different wallpaper for screen one')
    targets = {'94': 0, '95': 1}
    records = {
        '94': {'path': str(first), 'sha256': engine.sha256(first)},
        '95': {'path': str(second), 'sha256': engine.sha256(second)},
    }
    calls = []
    monkeypatch.setattr(engine, '_scheme_id', lambda value: value)
    monkeypatch.setattr(engine, '_apply_colors', lambda *_: None)
    monkeypatch.setattr(engine, '_restore_key', lambda *_: None)
    monkeypatch.setattr(engine, '_run', lambda image, one, **kw: calls.append((Path(image), one, kw)))
    monkeypatch.setattr(engine, '_verify', lambda _image, one: len(one) == 1)
    prior = {
        'color': 'Sweet-Ambar-Blue', 'local_color': None, 'local_hash': None,
        'konsole': 'Vapor', 'wallpaper_backups': records,
    }
    assert engine.restore_previous(prior, targets) == []
    assert calls == [
        (first, {'94': 0}, {'allow_partial': True}),
        (second, {'95': 1}, {'allow_partial': True}),
    ]


def test_lock_prevents_second_operation(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, 'ROOT', tmp_path)
    with engine.exclusive_operation():
        with pytest.raises(RuntimeError, match='Another KDE Dynamic Themes operation'):
            with engine.exclusive_operation():
                pass
