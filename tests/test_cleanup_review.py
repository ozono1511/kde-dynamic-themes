from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from review_cleanup import inventory, reachable, source_imports


def test_static_graph_follows_all_relative_imports(tmp_path):
    src = tmp_path / 'pkg'
    src.mkdir()
    (src / '__main__.py').write_text('from . import ui\n')
    (src / 'ui.py').write_text('from .engine import apply\n')
    (src / 'engine.py').write_text('from .snapshot import sha256\n')
    (src / 'snapshot.py').write_text('def sha256(): pass\n')
    (src / 'unused.py').write_text('pass\n')
    graph = source_imports(src)
    assert reachable(graph) == ['__main__', 'engine', 'snapshot', 'ui']
    assert set(graph) - set(reachable(graph)) == {'unused'}


def test_audit_is_read_only_and_protects_active_versions(tmp_path):
    project = tmp_path / 'project'
    app = project / 'app'
    app.mkdir(parents=True)
    for name in ('gallery_v1_2.py', 'gallery_v2_5.py', 'gallery_v2_6.py', 'theme_v2_3.py', 'theme_v2_0.py'):
        (app / name).write_text('pass')
    protected = project / 'backups'
    protected.mkdir()
    (protected / 'keep-me.txt').write_text('secret')
    home = tmp_path/'home'
    scheme_folder = home/'.local/share/color-schemes'
    scheme_folder.mkdir(parents=True)
    (scheme_folder/'KDTexample.colors').write_text('[General]')
    before = sorted(str(x.relative_to(tmp_path)) for x in tmp_path.rglob('*'))
    result = inventory(project, tmp_path/'missing-src', home)
    after = sorted(str(x.relative_to(tmp_path)) for x in tmp_path.rglob('*'))
    assert before == after
    assert result['read_only']
    assert result['historical_gallery_candidates'] == [str(app/'gallery_v1_2.py')]
    assert result['legacy_engine_candidates'] == [str(app/'theme_v2_0.py')]
    assert result['generated_schemes_protected'] == [str(scheme_folder/'KDTexample.colors')]
    assert (protected/'keep-me.txt').read_text() == 'secret'


def test_bytecode_detected_but_no_changes(tmp_path):
    project=tmp_path/'p'
    cache=project/'app/__pycache__'
    cache.mkdir(parents=True)
    bytecode=cache/'ui.cpython-314.pyc'
    bytecode.write_bytes(b'fake')
    result=inventory(project,tmp_path/'missing-source',tmp_path/'home')
    assert result['bytecode_candidates']==[str(bytecode)]
    assert bytecode.read_bytes()==b'fake'
