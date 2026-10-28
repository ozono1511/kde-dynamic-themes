import os

os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')

import pytest
from PySide6.QtWidgets import QApplication, QDialog

from kde_dynamic_themes.ui import MonitorSelectionDialog, monitor_dialog_result


@pytest.fixture(scope='module')
def qapp():
    return QApplication.instance() or QApplication([])


def monitor(cid, screen, *, name=None):
    return {
        'containment_id': cid,
        'screen': screen,
        'name': name,
        'manufacturer': None,
        'model': None,
        'geometry': {'x': screen * 1920, 'y': 0, 'width': 1920, 'height': 1080},
        'pixel_size': {'width': 1920, 'height': 1080},
        'refresh_rate': None,
    }


def test_monitor_dialog_requires_detected_monitors(qapp):
    with pytest.raises(ValueError, match='did not identify any physical monitors'):
        MonitorSelectionDialog([])


def test_one_monitor_selection_and_unavailable_fields_are_clear(qapp):
    dialog = MonitorSelectionDialog([monitor('42', 0, name='DP-1')])
    assert dialog.summary.text() == '1 of 1 monitors selected'
    assert 'DP-1' in dialog.checkboxes['42'].text()
    assert 'Model unavailable' in dialog.checkboxes['42'].text()
    assert 'Refresh rate unavailable' in dialog.checkboxes['42'].text()
    dialog.confirm_selection()
    assert dialog.targets == {'42': 0}


def test_two_monitor_partial_and_select_all_actions(qapp):
    dialog = MonitorSelectionDialog([monitor('94', 0), monitor('95', 1)])
    dialog.checkboxes['95'].setChecked(False)
    assert dialog.summary.text() == '1 of 2 monitors selected'
    dialog.confirm_selection()
    assert dialog.targets == {'94': 0}

    dialog = MonitorSelectionDialog([monitor('94', 0), monitor('95', 1)], initially_selected=[])
    assert not dialog.confirm_button.isEnabled()
    dialog.select_all_button.click()
    assert dialog.summary.text() == '2 of 2 monitors selected'
    dialog.confirm_button.click()
    assert dialog.targets == {'94': 0, '95': 1}


def test_clear_cancel_and_close_never_return_targets(qapp):
    dialog = MonitorSelectionDialog([monitor('94', 0), monitor('95', 1)])
    dialog.clear_button.click()
    assert dialog.summary.text() == '0 of 2 monitors selected'
    assert not dialog.confirm_button.isEnabled()
    dialog.cancel_button.click()
    assert monitor_dialog_result(dialog, dialog.result()) is None

    closed = MonitorSelectionDialog([monitor('94', 0)])
    closed.close()
    assert monitor_dialog_result(closed, closed.result()) is None
