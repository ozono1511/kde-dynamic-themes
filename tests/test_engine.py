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
    monkeypatch.setattr(engine, '_safe_image', lambda path: Path(path))
    monkeypatch.setattr(engine, 'preflight', lambda: None)
    monkeypatch.setattr(engine, 'create_baseline', lambda: {})
    monkeypatch.setattr(engine, 'validate_baseline', lambda b: None)
    monkeypatch.setattr(engine, 'current_state', lambda: {
        'image': str(old), 'konsole': 'Vapor', 'color': 'SweetAmbarBlue',
        'local_color': 'SweetAmbarBlue', 'local_hash': None,
    })
    monkeypatch.setattr(engine, '_scheme_id', lambda x: x)
    monkeypatch.setattr(engine, 'extract', lambda palette, mode: {'primary': '1,2,3'})
    monkeypatch.setattr(engine, 'kde_scheme', lambda *args: 'KDE colors\n')
    monkeypatch.setattr(engine, 'konsole_scheme', lambda *args: 'Konsole colors\n')
    def fail_apply(*args):
        raise RuntimeError('fake Plasma apply failure')
    monkeypatch.setattr(engine, '_apply_colors', fail_apply)
    verified = []
    def pretend_recovered(prior):
        b = Path(prior['image_backup'])
        assert b.read_bytes() == old.read_bytes()
        assert prior['image_sha256'] == engine.sha256(b)
        verified.append(True)
        return []
    monkeypatch.setattr(engine, 'restore_previous', pretend_recovered)
    with pytest.raises(RuntimeError, match='Theme application failed'):
        engine.apply(new, {}, 'dark')
    assert verified
    assert not (tmp_path/'config/transaction.json').exists()
    assert len(list((tmp_path/'backup').glob('tx-previous-*'))) == 1
    assert old.read_bytes() == b'old image, must survive the failed attempt'


def test_lock_prevents_second_operation(tmp_path, monkeypatch):
    monkeypatch.setattr(engine, 'ROOT', tmp_path)
    with engine.exclusive_operation():
        with pytest.raises(RuntimeError, match='Another KDE Dynamic Themes operation'):
            with engine.exclusive_operation():
                pass
