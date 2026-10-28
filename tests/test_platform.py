import json
from pathlib import Path
from types import SimpleNamespace

import pytest
from kde_dynamic_themes.wallpaper import build_apply_script

from kde_dynamic_themes.platform import (
    active_targets, detect_distro, diagnostic, discover_wallpaper_ids,
    parse_os_release, read_host_config, resolve_containment_ids,
    resolve_active_desktop_map, validate_target_map, query_plasma_desktops,
    save_containment_ids, physical_monitor_records, selected_monitor_targets,
)


def plasma_config(*ids):
    return '\n'.join(f'[Containments][{cid}][Wallpaper][org.kde.image][General]\nImage=file:///tmp/a.png' for cid in ids)


def test_os_detect_fedora_arch_bazzite():
    assert detect_distro(parse_os_release('ID=bazzite\nPRETTY_NAME="Bazzite"'), True).family == 'fedora-atomic'
    assert detect_distro({'ID': 'fedora'}, False).family == 'fedora'
    assert detect_distro({'ID': 'arch'}, False).family == 'arch'
    assert not detect_distro({'ID': 'debian'}, False).supported_profile


def test_containment_detection_does_not_assume_94_95():
    text = plasma_config(32, 5)
    assert discover_wallpaper_ids(text) == {'32', '5'}
    assert resolve_containment_ids(text) == {'32', '5'}


def test_ambiguous_mapping_requires_override():
    text = plasma_config(94, 95, 96)
    with pytest.raises(ValueError, match='Expected exactly 2'):
        resolve_containment_ids(text)
    assert resolve_containment_ids(text, ['94', '95']) == {'94', '95'}
    with pytest.raises(ValueError, match='absent'):
        resolve_containment_ids(text, ['94', '99'])
    with pytest.raises(ValueError, match='unique'):
        resolve_containment_ids(text, ['94', '94'])


def live_desktops(*items, screen_count=2):
    return {'screen_count': screen_count, 'desktops': [
        {'id': cid, 'screen': screen, 'wallpaperPlugin': plugin}
        for cid, screen, plugin in items
    ]}


def test_live_discovery_selects_active_screens_and_preserves_residual():
    raw = plasma_config(94, 95, 239)
    live = live_desktops(('94', 0, 'org.kde.image'), ('95', 1, 'org.kde.image'),
                         ('239', -1, 'org.kde.image'))
    assert resolve_active_desktop_map(raw, live) == {'94': 0, '95': 1}
    assert validate_target_map({'94': 0, '95': 1}, live) == live
    assert discover_wallpaper_ids(raw) == {'94', '95', '239'}


def test_active_mapping_rejects_missing_duplicate_and_stale_ids():
    raw = plasma_config(94, 95, 239)
    live = live_desktops(('94', 0, 'org.kde.image'), ('95', 1, 'org.kde.image'),
                         ('239', -1, 'org.kde.image'))
    with pytest.raises(ValueError, match='absent'):
        resolve_active_desktop_map(raw, live, ['94', '99'])
    with pytest.raises(ValueError, match='unique'):
        resolve_active_desktop_map(raw, live, ['94', '94'])
    ambiguous = live_desktops(('94', 0, 'org.kde.image'), ('96', 0, 'org.kde.image'),
                              ('95', 1, 'org.kde.image'))
    with pytest.raises(ValueError, match='multiple eligible'):
        resolve_active_desktop_map(plasma_config(94, 95, 96), ambiguous)
    assert resolve_active_desktop_map(plasma_config(94, 95, 96), ambiguous,
                                      ['94', '95']) == {'94': 0, '95': 1}


def test_monitor_count_change_uses_new_live_screen_inventory():
    raw = plasma_config(94, 95, 239)
    live = live_desktops(('94', 0, 'org.kde.image'), ('95', 1, 'org.kde.image'),
                         ('239', 2, 'org.kde.image'), screen_count=3)
    assert resolve_active_desktop_map(raw, live) == {'94': 0, '95': 1, '239': 2}
    with pytest.raises(ValueError, match='every current screen'):
        resolve_active_desktop_map(raw, live, ['94', '95'])
    with pytest.raises(ValueError, match='expects 2 monitors'):
        resolve_active_desktop_map(raw, live, expected_count=2)


def test_target_map_detects_live_screen_change():
    live = live_desktops(('94', 1, 'org.kde.image'), ('95', 0, 'org.kde.image'))
    with pytest.raises(ValueError, match='no longer active'):
        validate_target_map({'94': 0}, live)


def test_plasma_dbus_inventory_parser_uses_printed_json():
    payload = {'screenCount': 2, 'desktops': [
        {'id': '94', 'screen': 0, 'wallpaperPlugin': 'org.kde.image'},
        {'id': '95', 'screen': 1, 'wallpaperPlugin': 'org.kde.image'},
        {'id': '239', 'screen': -1, 'wallpaperPlugin': 'org.kde.image'},
    ], 'screens': [
        {'index': 0, 'geometry': {'x': 0, 'y': 0, 'width': 2560, 'height': 1440}},
        {'index': 1, 'geometry': {'x': 2560, 'y': 0, 'width': 2560, 'height': 1440}},
    ]}
    called = []
    result = query_plasma_desktops(
        command_lookup=lambda name: '/usr/bin/qdbus' if name == 'qdbus' else None,
        run=lambda args, **_kwargs: (called.extend(args) or SimpleNamespace(
            returncode=0, stdout='KDT_DESKTOPS:' + json.dumps(payload), stderr='')),
    )
    assert 'desktopsForActivity(currentActivity())' in called[-1]
    assert result['screen_count'] == 2
    assert [(item['id'], item['screen']) for item in result['desktops']] == [
        ('94', 0), ('95', 1), ('239', -1)]


def test_plasma_dbus_inventory_fails_closed_without_unique_result():
    with pytest.raises(RuntimeError, match='no unique desktop inventory'):
        query_plasma_desktops(
            command_lookup=lambda _name: '/usr/bin/qdbus',
            run=lambda *_args, **_kwargs: SimpleNamespace(returncode=0, stdout='', stderr=''),
        )


def test_plasma_dbus_rejects_incomplete_and_failed_responses():
    with pytest.raises(RuntimeError, match='incomplete screen inventory'):
        query_plasma_desktops(
            command_lookup=lambda _name: '/usr/bin/qdbus',
            run=lambda *_args, **_kwargs: SimpleNamespace(
                returncode=0, stdout='KDT_DESKTOPS:' + json.dumps({'screenCount': 1, 'desktops': []}), stderr=''),
        )
    with pytest.raises(RuntimeError, match='over the user D-Bus session'):
        query_plasma_desktops(
            command_lookup=lambda _name: '/usr/bin/qdbus',
            run=lambda *_args, **_kwargs: SimpleNamespace(returncode=1, stdout='', stderr='AccessDenied'),
        )


def test_physical_monitor_association_uses_geometry_and_contains_only_active_ids():
    live = {'screen_count': 2, 'screens': [
        {'index': 0, 'geometry': {'x': 0, 'y': 0, 'width': 2560, 'height': 1440}},
        {'index': 1, 'geometry': {'x': 2560, 'y': 0, 'width': 2560, 'height': 1440}},
    ], 'desktops': [
        {'id': '94', 'screen': 0, 'wallpaperPlugin': 'org.kde.image'},
        {'id': '95', 'screen': 1, 'wallpaperPlugin': 'org.kde.image'},
        {'id': '239', 'screen': -1, 'wallpaperPlugin': 'org.kde.image'},
    ]}
    outputs = [
        {'name': 'DP-3', 'manufacturer': 'Vendor', 'model': 'Display A', 'serial_number': None,
         'geometry': {'x': 2560, 'y': 0, 'width': 2560, 'height': 1440},
         'pixel_size': {'width': 2560, 'height': 1440}, 'refresh_rate': 144.0},
        {'name': 'HDMI-A-1', 'manufacturer': None, 'model': 'Display B', 'serial_number': None,
         'geometry': {'x': 0, 'y': 0, 'width': 2560, 'height': 1440},
         'pixel_size': {'width': 2560, 'height': 1440}, 'refresh_rate': 60.0},
    ]
    monitors = physical_monitor_records({'94': 0, '95': 1}, live, outputs)
    assert [(item['name'], item['containment_id']) for item in monitors] == [
        ('HDMI-A-1', '94'), ('DP-3', '95')]
    assert '239' not in {item['containment_id'] for item in monitors}


def test_physical_monitor_association_fails_on_missing_or_ambiguous_geometry():
    live = {'screen_count': 1, 'screens': [
        {'index': 0, 'geometry': {'x': 0, 'y': 0, 'width': 1920, 'height': 1080}},
    ], 'desktops': [{'id': '42', 'screen': 0, 'wallpaperPlugin': 'org.kde.image'}]}
    with pytest.raises(ValueError, match='different monitor counts'):
        physical_monitor_records({'42': 0}, live, [])
    outputs = [{'geometry': {'x': 10, 'y': 0, 'width': 1920, 'height': 1080}}]
    with pytest.raises(ValueError, match='cannot be matched uniquely'):
        physical_monitor_records({'42': 0}, live, outputs)


def test_monitor_selection_one_two_partial_all_and_invalid_ids():
    one = [{'containment_id': '42', 'screen': 0}]
    two = [{'containment_id': '94', 'screen': 0}, {'containment_id': '95', 'screen': 1}]
    assert selected_monitor_targets(one, ['42']) == {'42': 0}
    assert selected_monitor_targets(two, ['94']) == {'94': 0}
    assert selected_monitor_targets(two, ['94', '95']) == {'94': 0, '95': 1}
    with pytest.raises(ValueError, match='any physical monitors'):
        selected_monitor_targets([], [])
    with pytest.raises(ValueError, match='duplicate'):
        selected_monitor_targets(two, ['94', '94'])
    with pytest.raises(ValueError, match='not in the current'):
        selected_monitor_targets(two, ['239'])


def test_apply_script_scopes_write_to_selected_desktops_only():
    script = build_apply_script('file:///tmp/theme.png', {'94': 0, '95': 1}, 2)
    assert r'\"id\":\"94\",\"screen\":0' in script
    assert r'\"id\":\"95\",\"screen\":1' in script
    assert '239' not in script
    assert 'selected.forEach' in script


def test_host_config_rejects_unknown_keys(tmp_path):
    p = tmp_path / 'host.json'
    p.write_text(json.dumps({'unexpected_private_value': 'sensitive'}))
    with pytest.raises(ValueError, match='Unknown host settings'):
        read_host_config(p)
    p.write_text(json.dumps({'containment_ids': ['10','11'], 'konsole_profile': 'Default.profile'}))
    assert read_host_config(p)['konsole_profile'] == 'Default.profile'


def test_saving_manual_mapping_preserves_settings_and_backs_up_prior(tmp_path, monkeypatch):
    import kde_dynamic_themes.platform as platform
    project = tmp_path/'project'
    host = project/'config/host.json'
    host.parent.mkdir(parents=True)
    host.write_text(json.dumps({'containment_ids': ['10', '11'], 'expected_monitors': 2,
                                'konsole_profile': 'Default.profile'}))
    monkeypatch.setattr(platform, 'HOST_FILE', host)
    monkeypatch.setattr(platform, 'PROJECT_ROOT', project)
    backup = save_containment_ids(['21', '22'], expected_monitors=2)
    assert json.loads(host.read_text()) == {
        'containment_ids': ['21', '22'], 'expected_monitors': 2,
        'konsole_profile': 'Default.profile',
    }
    record = json.loads(backup.read_text())
    assert record['existed_before'] is True
    assert record['previous']['containment_ids'] == ['10', '11']


def test_diagnostic_is_read_only(tmp_path):
    cfg = tmp_path / 'appletsrc'
    cfg.write_text(plasma_config(121, 122))
    release = tmp_path / 'os-release'
    release.write_text('ID=arch\nPRETTY_NAME="Arch Linux"\n')
    result = diagnostic(project=tmp_path, config_path=cfg, os_release_path=release,
                        command_lookup=lambda tool: '/usr/bin/' + tool,
                        desktop_provider=lambda: live_desktops(
                            ('121', 0, 'org.kde.image'), ('122', 1, 'org.kde.image')))
    assert result['read_only']
    assert result['distro']['family'] == 'arch'
    assert result['containment_ids'] == ['121','122']
    assert not result['issues']
    assert sorted(p.name for p in tmp_path.iterdir()) == ['appletsrc','os-release']


def test_single_monitor_profile():
    assert resolve_containment_ids(plasma_config(42), expected_count=1) == {"42"}
