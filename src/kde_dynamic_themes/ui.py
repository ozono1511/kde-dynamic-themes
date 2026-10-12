#!/usr/bin/env python3
"""KDE Dynamic Themes: wallpaper gallery, Matugen preview, and safe theme application."""
import json
import sys
import re
from collections import Counter
from pathlib import Path

from PySide6.QtCore import Qt, QSize, QProcess
from PySide6.QtGui import QColor, QIcon, QImageReader, QPixmap, QFont, QPalette
from PySide6.QtWidgets import (
    QApplication, QFileDialog, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMessageBox, QPushButton, QSplitter, QVBoxLayout, QWidget,
    QComboBox, QDoubleSpinBox, QInputDialog, QDialog,
)

from .engine import apply as apply_theme_direct, recover_baseline, JOURNAL

from .paths import PROJECT_ROOT
ROOT = PROJECT_ROOT
WALLPAPERS = ROOT / 'wallpapers'
SOURCES_FILE = ROOT / 'config' / 'wallpaper-sources.json'
EXTENSIONS = {'.png', '.jpg', '.jpeg', '.webp', '.bmp'}
MAX_FILES = 500
MATUGEN = ROOT / 'bin' / 'matugen'
PALETTES = ROOT / 'palettes'
SCHEMES = ['scheme-tonal-spot', 'scheme-vibrant', 'scheme-expressive',
           'scheme-fidelity', 'scheme-content', 'scheme-neutral', 'scheme-monochrome']
COLOR_KEYS = ['background', 'surface', 'surface_container', 'on_surface',
              'primary', 'on_primary', 'secondary', 'tertiary', 'outline']


APP_STYLESHEET = """
QWidget { background-color: #15171c; color: #e8eaf0; font-size: 12px; }
QLabel#appTitle { font-size: 19px; font-weight: 700; letter-spacing: 2px; color: #e6e8ee; }
QLabel#sectionLabel { font-size: 10px; font-weight: 700; color: #9299aa; letter-spacing: 1px; }
QLabel#wallpaperPreview { background: #20242d; border: 1px solid #323844; border-radius: 10px; padding: 5px; }
QLabel#statusLabel { color: #a7afbf; font-size: 11px; }
QListWidget#wallpaperGallery { background: #1b1e25; border: 1px solid #313641; border-radius: 10px; padding: 8px; outline: none; }
QListWidget#wallpaperGallery::item { border: 1px solid transparent; border-radius: 7px; padding: 4px; }
QListWidget#wallpaperGallery::item:selected { background: #313b50; border: 1px solid #7d94be; color: #ffffff; }
QPushButton { background: #272c36; border: 1px solid #3b4250; border-radius: 8px; padding: 8px 13px; }
QPushButton:hover { background: #343b49; }
QPushButton:disabled { color: #767c88; background: #21242a; }
QPushButton#primaryButton { background: #536b97; border: 1px solid #748bb7; font-weight: 700; color: white; }
QPushButton#primaryButton:hover { background: #637dab; }
QPushButton#quietButton { background: #22262e; border-color: #323844; }
QComboBox, QDoubleSpinBox { background: #242933; border: 1px solid #3b4350; border-radius: 7px; padding: 6px; min-height: 20px; }
QComboBox QAbstractItemView { background: #242933; color: #e8eaf0; selection-background-color: #536b97; }
QSplitter::handle { background: #15171c; width: 12px; }
QMessageBox { background: #1b1e25; }
"""

def read_image(path, max_size):
    reader = QImageReader(str(path))
    reader.setAutoTransform(True)
    if not reader.canRead():
        return None
    size = reader.size()
    if size.isValid():
        size.scale(max_size, Qt.AspectRatioMode.KeepAspectRatio)
        reader.setScaledSize(size)
    image = reader.read()
    return image if not image.isNull() else None


def palette_for(path):
    """Small, deterministic approximate palette; not a Matugen replacement."""
    image = read_image(path, QSize(96, 96))
    if image is None:
        return []
    counts = Counter()
    for y in range(0, image.height(), 2):
        for x in range(0, image.width(), 2):
            c = QColor(image.pixel(x, y))
            if c.alpha() < 128:
                continue
            # Coarse RGB histogram: efficient and dependency-free.
            key = (c.red() // 32, c.green() // 32, c.blue() // 32)
            counts[key] += 1
    chosen = []
    for (r, g, b), _ in counts.most_common():
        color = QColor(min(255, r * 32 + 16), min(255, g * 32 + 16), min(255, b * 32 + 16))
        if all(abs(color.red()-old.red()) + abs(color.green()-old.green()) + abs(color.blue()-old.blue()) > 105 for old in chosen):
            chosen.append(color)
        if len(chosen) == 5:
            break
    return chosen


class Gallery(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('KDE Dynamic Themes')
        self.resize(960, 600)
        self.current_path = None
        self.generated_palette = None
        self.generated_context = None
        self.process = None
        self.pending_generation = False
        self.sources = self.load_sources()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(20, 18, 20, 16)
        layout.setSpacing(14)
        top = QHBoxLayout()
        title = QLabel('DYNAMIC THEMES')
        title.setObjectName('appTitle')
        top.addWidget(title)
        top.addStretch()
        settings = QPushButton('⚙  Settings')
        settings.setObjectName('quietButton')
        settings.clicked.connect(self.open_advanced)
        top.addWidget(settings)
        layout.addLayout(top)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setIconSize(QSize(160, 90))
        self.list.setGridSize(QSize(182, 108))
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setWordWrap(True)
        self.list.setSpacing(5)
        self.list.setObjectName('wallpaperGallery')
        self.list.currentItemChanged.connect(self.show_preview)
        splitter.addWidget(self.list)
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(10)
        self.preview = QLabel('Select an image')
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(310, 205)
        self.preview.setObjectName('wallpaperPreview')
        right_layout.addWidget(self.preview, 1)
        # Palette preview uses actual Matugen colors, not an approximate histogram.
        self.color_labels = []
        palette_header = QHBoxLayout()
        palette_title = QLabel('THEME COLORS')
        palette_title.setObjectName('sectionLabel')
        palette_header.addWidget(palette_title)
        palette_header.addStretch()
        right_layout.addLayout(palette_header)
        self.palette_labels = []
        palette_row = QHBoxLayout()
        for key in COLOR_KEYS:
            label = QLabel('—')
            label.setFixedHeight(36)
            label.setMinimumWidth(12)
            label.setToolTip(key)
            self.palette_labels.append(label)
            palette_row.addWidget(label, 1)
        right_layout.addLayout(palette_row)
        options = QHBoxLayout()
        options.addWidget(QLabel('Mode'))
        self.mode = QComboBox()
        self.mode.addItems(['dark', 'light'])
        self.mode.currentIndexChanged.connect(self.generate_palette)
        options.addWidget(self.mode)
        self.scheme = QComboBox()
        self.scheme.addItems(SCHEMES)
        self.scheme.setCurrentText('scheme-tonal-spot')
        self.scheme.currentIndexChanged.connect(self.generate_palette)
        self.contrast = QDoubleSpinBox()
        self.contrast.setRange(-1.0, 1.0)
        self.contrast.setSingleStep(0.1)
        self.contrast.setValue(0.0)
        self.contrast.valueChanged.connect(self.generate_palette)
        options.addStretch()
        right_layout.addLayout(options)
        action_row = QHBoxLayout()
        apply_button = QPushButton('Apply Theme')
        apply_button.setObjectName('primaryButton')
        apply_button.setMinimumHeight(44)
        apply_button.clicked.connect(self.apply_theme_simple)
        action_row.addWidget(apply_button, 1)
        right_layout.addLayout(action_row)
        self.info = QLabel('Select a wallpaper. Preview does not change your desktop.')
        self.info.setObjectName('statusLabel')
        self.info.setWordWrap(True)
        right_layout.addWidget(self.info)
        splitter.addWidget(right)
        splitter.setSizes([520, 430])
        layout.addWidget(splitter, 1)
        self.setWindowTitle('KDE Dynamic Themes')
        self.resize(960, 600)
        self.setMinimumSize(750, 480)
        self.setStyleSheet(APP_STYLESHEET)
        self.load_images()

    def load_sources(self):
        if not SOURCES_FILE.is_file():
            return []
        try:
            data = json.loads(SOURCES_FILE.read_text(encoding='utf-8'))
            if not isinstance(data, list):
                return []
            return [str(Path(p).expanduser()) for p in data if isinstance(p, str) and Path(p).is_dir()]
        except (OSError, ValueError):
            return []

    def save_sources(self):
        # Only project-local configuration; never touches KDE or source directories.
        SOURCES_FILE.parent.mkdir(parents=True, exist_ok=True)
        SOURCES_FILE.write_text(json.dumps(self.sources, indent=2, ensure_ascii=False) + '\n', encoding='utf-8')

    def add_folder(self):
        folder = QFileDialog.getExistingDirectory(self, 'Add wallpaper folder', str(Path.home()))
        if not folder:
            return
        folder = str(Path(folder).resolve())
        if folder not in self.sources and folder != str(WALLPAPERS):
            self.sources.append(folder)
            self.save_sources()
        self.load_images()

    def remove_folder(self):
        if not self.sources:
            QMessageBox.information(self, 'Folders', 'No external folders have been added.')
            return
        choices = '\n'.join(f'{i+1}. {path}' for i, path in enumerate(self.sources))
        from PySide6.QtWidgets import QInputDialog
        number, ok = QInputDialog.getInt(self, 'Remove folder',
            f'Registered folders:\n{choices}\n\nFolder number to remove:', 1, 1, len(self.sources))
        if ok:
            self.sources.pop(number-1)
            self.save_sources()
            self.load_images()

    def load_images(self):
        self.list.clear()
        self.current_path = None
        self.reset_palette()
        self.preview.clear()
        self.preview.setText('Select an image')
        for label in self.color_labels:
            label.setText('—')
            label.setStyleSheet('')
        seen = set()
        total = 0
        for directory in [WALLPAPERS] + [Path(p) for p in self.sources]:
            if not directory.is_dir():
                continue
            try:
                entries = sorted(directory.iterdir(), key=lambda p: p.name.lower())
            except OSError:
                continue
            for path in entries:
                if total >= MAX_FILES:
                    break
                if not path.is_file() or path.suffix.lower() not in EXTENSIONS:
                    continue
                canonical = str(path.resolve())
                if canonical in seen:
                    continue
                seen.add(canonical)
                image = read_image(path, QSize(150, 90))
                if image is None:
                    continue
                item = QListWidgetItem(QIcon(QPixmap.fromImage(image)), "")
                item.setData(Qt.ItemDataRole.UserRole, str(path))
                item.setToolTip(path.name)
                self.list.addItem(item)
                total += 1
            if total >= MAX_FILES:
                break
        if self.list.count():
            self.list.setCurrentRow(0)
        else:
            self.info.setText('Gallery is empty. Use Settings → Add Images.')
        if total >= MAX_FILES:
            self.info.setText(f'Showing at most {MAX_FILES} images. Add smaller folders for easier browsing.')


    def show_preview(self, current, previous):
        if current:
            self.render(Path(current.data(Qt.ItemDataRole.UserRole)))

    def render(self, path):
        image = read_image(path, QSize(1600, 1000))
        if image is None:
            self.info.setText('Could not open image.')
            return
        self.current_path = path
        self.reset_palette()
        self.current_pixmap = QPixmap.fromImage(image)
        self.update_preview()
        self.info.setText(f'{path.name} — in-app preview; KDE unchanged.')
        self.generate_palette()

    def reset_palette(self):
        self.generated_palette = None
        self.generated_context = None
        self.setStyleSheet(APP_STYLESHEET)
        for key, label in zip(COLOR_KEYS, self.palette_labels):
            label.setText('—')
            label.setStyleSheet('')

    def generate_palette(self):
        if self.process is not None and self.process.state() != QProcess.ProcessState.NotRunning:
            self.pending_generation = True
            return
        if not self.current_path or not self.current_path.is_file():
            QMessageBox.warning(self, 'Matugen', 'Select a valid wallpaper.')
            return
        if not MATUGEN.is_file():
            QMessageBox.warning(self, 'Matugen', f'Executable not found: {MATUGEN}')
            return
        self.reset_palette()
        self.info.setText('Generating palette… KDE remains unchanged.')
        self.generated_context = {
            'wallpaper': str(self.current_path.resolve()),
            'mode': self.mode.currentText(),
            'scheme': self.scheme.currentText(),
            'contrast': self.contrast.value(),
        }
        self.process = QProcess(self)
        self.process.setProgram(str(MATUGEN))
        self.process.setArguments([
            'image', str(self.current_path), '--mode', self.mode.currentText(),
            '--type', self.scheme.currentText(), '--contrast', str(self.contrast.value()),
            '--source-color-index', '0', '--json', 'hex', '--dry-run',
        ])
        self.process.finished.connect(self.palette_finished)
        self.process.errorOccurred.connect(self.palette_error)
        self.process.start()

    def palette_error(self, error):
        if self.process and self.process.state() == QProcess.ProcessState.NotRunning:
            self.info.setText(f'Could not start Matugen: {self.process.errorString()}')
            stale = self.process
            self.process = None
            stale.deleteLater()

    def palette_finished(self, exit_code, exit_status):
        process = self.process
        if process is None:
            return
        output = bytes(process.readAllStandardOutput()).decode('utf-8', errors='replace')
        error = bytes(process.readAllStandardError()).decode('utf-8', errors='replace')
        self.process = None
        process.deleteLater()
        if self.pending_generation:
            self.pending_generation = False
            self.generate_palette()
            return
        if exit_code != 0 or exit_status != QProcess.ExitStatus.NormalExit:
            self.info.setText(f'Matugen failed: {error[:350]}')
            return
        if not self.generated_context or str(self.current_path.resolve()) != self.generated_context['wallpaper']:
            self.info.setText('Image changed during generation. Regenerate the palette.')
            return
        try:
            data = json.loads(output)
            colors = data['colors']
            variant = self.generated_context['mode']
            for key, label in zip(COLOR_KEYS, self.palette_labels):
                value = colors[key][variant]['color']
                if not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                    raise ValueError(f'Invalid color: {key}')
                c = QColor(value)
                fg = '#111111' if c.lightness() > 145 else '#ffffff'
                label.setText('')
                label.setToolTip(f'{key}: {value.upper()}')
                label.setStyleSheet(f'background: {value}; color: {fg}; border: 1px solid #444a55; border-radius: 6px;')
            self.generated_palette = data
            self.update_dynamic_style()
            self.info.setText('Preview ready. Your desktop has not changed.')
        except (ValueError, KeyError, TypeError) as exc:
            self.info.setText(f'Unexpected Matugen JSON: {exc}')














    def update_dynamic_style(self):
        """Use Matugen primary to tint a stable, readable dark UI (preview only)."""
        if not self.generated_palette or not self.generated_context:
            self.setStyleSheet(APP_STYLESHEET)
            return
        try:
            colors = self.generated_palette['colors']
            # Dark remains the fixed UI base, independent of desktop mode.
            def role(name):
                value = colors[name]['dark']['color']
                if not isinstance(value, str) or not re.fullmatch(r'#[0-9a-fA-F]{6}', value):
                    raise ValueError('Invalid Matugen color: ' + name)
                return QColor(value)
            primary = role('primary')
            role('on_primary')
            def blend(base, accent, weight):
                a = QColor(base)
                def channel(x, y):
                    return round(x * (1.0 - weight) + y * weight)
                return QColor(channel(a.red(), accent.red()),
                              channel(a.green(), accent.green()),
                              channel(a.blue(), accent.blue())).name()
            def readable(bg):
                c = QColor(bg)
                return '#11141a' if c.lightness() > 155 else '#f3f5f8'
            background = blend('#12161b', primary, 0.11)
            surface = blend('#1b2027', primary, 0.22)
            surface_high = blend('#292f38', primary, 0.27)
            surface_low = blend('#161a21', primary, 0.14)
            border = blend('#48505c', primary, 0.35)
            selected = blend('#303945', primary, 0.57)
            hover = blend('#333c48', primary, 0.44)
            accent = primary.name()
            foreground = '#f0f2f7'
            secondary = '#b6becb'
            on_accent = readable(accent)
            selected_text = readable(selected)
            style = f"""
                QWidget {{ background-color: {background}; color: {foreground}; font-size: 12px; }}
                QLabel#appTitle {{ font-size: 19px; font-weight: 700; letter-spacing: 2px; color: {foreground}; }}
                QLabel#sectionLabel {{ font-size: 10px; font-weight: 700; color: {secondary}; letter-spacing: 1px; }}
                QLabel#wallpaperPreview {{ background: {surface_low}; border: 1px solid {border}; border-radius: 10px; padding: 5px; }}
                QLabel#statusLabel {{ color: {secondary}; font-size: 11px; }}
                QListWidget#wallpaperGallery {{ background: {surface}; border: 1px solid {border}; border-radius: 10px; padding: 8px; outline: none; }}
                QListWidget#wallpaperGallery::item {{ border: 1px solid transparent; border-radius: 7px; padding: 4px; }}
                QListWidget#wallpaperGallery::item:selected {{ background: {selected}; border: 2px solid {accent}; color: {selected_text}; }}
                QPushButton {{ background: {surface_high}; color: {foreground}; border: 1px solid {border}; border-radius: 8px; padding: 8px 13px; }}
                QPushButton:hover {{ background: {hover}; }}
                QPushButton:disabled {{ color: {secondary}; background: {surface_low}; }}
                QPushButton#primaryButton {{ background: {accent}; border: 1px solid {accent}; font-weight: 700; color: {on_accent}; }}
                QPushButton#primaryButton:hover {{ background: {selected}; color: {selected_text}; border: 1px solid {accent}; }}
                QPushButton#quietButton {{ background: {surface}; border-color: {border}; }}
                QPushButton#quietButton:hover {{ background: {hover}; }}
                QComboBox, QDoubleSpinBox {{ background: {surface_high}; color: {foreground}; border: 1px solid {border}; border-radius: 7px; padding: 6px; min-height: 20px; }}
                QComboBox QAbstractItemView {{ background: {surface_high}; color: {foreground}; selection-background-color: {selected}; selection-color: {selected_text}; }}
                QSplitter::handle {{ background: {background}; width: 12px; }}
                QMessageBox, QDialog {{ background: {background}; color: {foreground}; }}
            """
            self.setStyleSheet(style)
            pal = self.palette()
            for role_id, value in (
                (QPalette.ColorRole.Window, background),
                (QPalette.ColorRole.WindowText, foreground),
                (QPalette.ColorRole.Base, surface),
                (QPalette.ColorRole.Text, foreground),
                (QPalette.ColorRole.Button, surface_high),
                (QPalette.ColorRole.ButtonText, foreground),
                (QPalette.ColorRole.Highlight, selected),
                (QPalette.ColorRole.HighlightedText, selected_text),
            ):
                pal.setColor(role_id, QColor(value))
            self.setPalette(pal)
        except (KeyError, ValueError, TypeError, AttributeError) as exc:
            self.setStyleSheet(APP_STYLESHEET)
            self.info.setText(f'Dynamic palette unavailable: {exc}')

    def apply_theme_simple(self):
        if not self.current_path or self.generated_palette is None:
            QMessageBox.information(self, 'Please wait', 'Select an image and wait for palette generation.')
            return
        if not self.generated_context or (
            str(self.current_path.resolve()) != self.generated_context.get('wallpaper')
            or self.mode.currentText() != self.generated_context.get('mode')
            or self.scheme.currentText() != self.generated_context.get('scheme')
            or abs(self.contrast.value() - self.generated_context.get('contrast', 999)) > 0.001
        ):
            QMessageBox.warning(self, 'Palette out of date', 'Wait for colors to finish updating before applying.')
            return
        if JOURNAL.exists():
            QMessageBox.warning(self, 'Recovery required',
                'A theme transition was interrupted. Use Settings → Restore Stable Baseline.')
            return
        answer = QMessageBox.question(self, 'Apply Theme',
            'Apply this wallpaper and its colors to Plasma and Konsole?\n'
            'The active theme will be replaced directly.')
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            result = apply_theme_direct(self.current_path, self.generated_palette, self.mode.currentText())
            QMessageBox.information(self, 'Theme applied', result)
        except Exception as exc:
            QMessageBox.critical(self, 'Application not completed', str(exc))

    def restore_stable(self):
        answer = QMessageBox.question(self, 'Restore Stable Baseline',
            'Apply a BLACK background on both monitors, Sweet-Ambar-Blue colors, and Konsole Vapor?\n'
            'This action always restores the stable baseline, not the previous theme.')
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            QMessageBox.information(self, 'Baseline restored', recover_baseline())
        except Exception as exc:
            QMessageBox.critical(self, 'Recovery incomplete', str(exc))

    def open_advanced(self):
        dialog = QDialog(self)
        dialog.setWindowTitle('Settings')
        dialog.resize(420, 255)
        layout = QVBoxLayout(dialog)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(10)
        label = QLabel('LIBRARY')
        label.setObjectName('sectionLabel')
        layout.addWidget(label)
        for title, callback in (
            ('Add Images', self.add_folder),
            ('Manage Folders', self.remove_folder),
        ):
            button = QPushButton(title)
            button.clicked.connect(callback)
            layout.addWidget(button)
        layout.addSpacing(8)
        label = QLabel('SAFETY')
        label.setObjectName('sectionLabel')
        layout.addWidget(label)
        recovery = QPushButton('Restore Stable Baseline (Black)')
        recovery.clicked.connect(self.restore_stable)
        layout.addWidget(recovery)
        note = QLabel('Baseline: black background, Sweet-Ambar-Blue, and Konsole Vapor.\n'
                      'Recovery requires confirmation.')
        note.setWordWrap(True)
        note.setObjectName('statusLabel')
        layout.addWidget(note)
        dialog.setStyleSheet(self.styleSheet())
        dialog.exec()

    def update_preview(self):
        if hasattr(self, 'current_pixmap'):
            self.preview.setPixmap(self.current_pixmap.scaled(
                self.preview.size(), Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_preview()


def main():
    app = QApplication(sys.argv)
    app.setApplicationName('KDE Dynamic Themes')
    app.setWindowIcon(QIcon.fromTheme('kde-dynamic-themes'))
    if hasattr(app, 'setDesktopFileName'):
        app.setDesktopFileName('kde-dynamic-themes')
    window = Gallery()
    window.show()
    return app.exec()


if __name__ == '__main__':
    sys.exit(main())
