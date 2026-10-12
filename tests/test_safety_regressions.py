from pathlib import Path
import hashlib
import json
import pytest

from kde_dynamic_themes import engine


def test_stable_black_png_content_deterministic():
    assert engine.black_png_bytes() == engine.black_png_bytes()
    assert engine.black_png_bytes().startswith(b'\x89PNG\r\n\x1a\n')


def test_black_wallpaper_tampering_blocks_recovery(tmp_path, monkeypatch):
    black = tmp_path/'baseline-black.png'
    monkeypatch.setattr(engine,'BLACK',black)
    assert engine.ensure_black()==black
    known=hashlib.sha256(black.read_bytes()).hexdigest()
    assert known == hashlib.sha256(engine.black_png_bytes()).hexdigest()
    black.write_bytes(b'untrusted change')
    with pytest.raises(RuntimeError,match='Stable black recovery image'):
        engine.ensure_black()
    assert black.read_bytes()==b'untrusted change'


def test_recovery_does_not_mutate_when_baseline_corrupted(tmp_path, monkeypatch):
    config=tmp_path/'config'
    config.mkdir()
    baseline=config/'baseline.json'
    baseline.write_text(json.dumps({'format': 'invalid'}))
    monkeypatch.setattr(engine,'BASELINE',baseline)
    monkeypatch.setattr(engine,'JOURNAL',config/'journal.json')
    monkeypatch.setattr(engine,'preflight_for_recovery',lambda: None)
    marker=[]
    monkeypatch.setattr(engine,'_apply_colors',lambda x: marker.append('applied'))
    with pytest.raises(RuntimeError,match='Invalid stable baseline'):
        engine._recover_baseline_unlocked()
    assert marker==[]
    assert not (config/'journal.json').exists()


def test_interrupted_journal_prevents_theme_apply(tmp_path, monkeypatch):
    journal=tmp_path/'journal.json'
    journal.write_text('{}')
    monkeypatch.setattr(engine,'JOURNAL',journal)
    monkeypatch.setattr(engine,'RECORD',tmp_path/'absent.json')
    with pytest.raises(RuntimeError,match='theme transition was interrupted'):
        engine.preflight()
    assert journal.read_text()=='{}'


def test_baseline_is_immutable_when_existing(tmp_path, monkeypatch):
    baseline=tmp_path/'baseline.json'
    baseline.write_text(json.dumps({'format': 'existing-baseline', 'backup': 'keep'}))
    monkeypatch.setattr(engine,'BASELINE',baseline)
    monkeypatch.setattr(engine,'preflight',lambda: (_ for _ in ()).throw(RuntimeError('should not preflight')))
    assert engine.create_baseline()['backup']=='keep'
    assert json.loads(baseline.read_text())['format']=='existing-baseline'
