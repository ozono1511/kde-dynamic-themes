import json
from pathlib import Path

import pytest

from kde_dynamic_themes.platform import (
    active_targets, detect_distro, diagnostic, discover_wallpaper_ids,
    parse_os_release, read_host_config, resolve_containment_ids,
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


def test_host_config_rejects_unknown_keys(tmp_path):
    p = tmp_path / 'host.json'
    p.write_text(json.dumps({'unexpected_private_value': 'sensitive'}))
    with pytest.raises(ValueError, match='Unknown host settings'):
        read_host_config(p)
    p.write_text(json.dumps({'containment_ids': ['10','11'], 'konsole_profile': 'Default.profile'}))
    assert read_host_config(p)['konsole_profile'] == 'Default.profile'


def test_diagnostic_is_read_only(tmp_path):
    cfg = tmp_path / 'appletsrc'
    cfg.write_text(plasma_config(121, 122))
    release = tmp_path / 'os-release'
    release.write_text('ID=arch\nPRETTY_NAME="Arch Linux"\n')
    result = diagnostic(project=tmp_path, config_path=cfg, os_release_path=release,
                        command_lookup=lambda tool: '/usr/bin/' + tool)
    assert result['read_only']
    assert result['distro']['family'] == 'arch'
    assert result['containment_ids'] == ['121','122']
    assert not result['issues']
    assert sorted(p.name for p in tmp_path.iterdir()) == ['appletsrc','os-release']


def test_single_monitor_profile():
    assert resolve_containment_ids(plasma_config(42), expected_count=1) == {"42"}
