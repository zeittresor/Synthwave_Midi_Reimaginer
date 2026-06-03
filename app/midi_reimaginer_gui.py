#!/usr/bin/env python3
# source: https://github.com/zeittresor/Synthwave_Midi_Reimaginer
"""
PyQt6 GUI for Synthwave MIDI Reimaginer.
"""
from __future__ import annotations

import json
import re
import sys
import traceback
from pathlib import Path
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt, QUrl
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox,
    QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel, QLineEdit,
    QTextEdit, QCheckBox, QComboBox, QSlider, QProgressBar, QGroupBox,
    QSpinBox, QTabWidget, QScrollArea
)

# Allow running directly from app folder or project root.
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import midi_reimaginer_core as core

APP_VERSION = "0.2.6"
THEME_DIR = APP_DIR / "themes"
LANG_DIR = APP_DIR / "lang"


@dataclass
class JobSettings:
    source: Path
    output_dir: Path
    prefix: str
    render_audio: bool
    render_mp3: bool
    sample_rate: int
    intensity: float
    target_bpm: float
    repetition: float
    use_style_instruments: bool
    harmony_lock: bool
    seed: int | None
    style_id: str
    random_style: bool


class AnalyzeWorker(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, source: Path):
        super().__init__()
        self.source = source

    def run(self):
        try:
            self.log.emit(f"[0%] Starting analysis worker for {self.source.name}")
            result = core.analyze_midi(self.source, progress=lambda text: self.log.emit(str(text)))
            self.finished.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class RenderWorker(QObject):
    log = pyqtSignal(str)
    finished = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, settings: JobSettings):
        super().__init__()
        self.settings = settings

    def run(self):
        try:
            s = self.settings
            self.log.emit(f"[0%] Starting render worker for {s.source.name}")
            result = core.process_file(
                s.source,
                output_dir=s.output_dir,
                prefix=s.prefix,
                render_audio=s.render_audio,
                render_mp3=s.render_mp3,
                sample_rate=s.sample_rate,
                intensity=s.intensity,
                target_bpm=s.target_bpm,
                repetition=s.repetition,
                use_style_instruments=s.use_style_instruments,
                harmony_lock=s.harmony_lock,
                seed=s.seed,
                style_id=s.style_id,
                random_style=s.random_style,
                progress=lambda text: self.log.emit(str(text)),
            )
            self.finished.emit(result)
        except Exception:
            self.failed.emit(traceback.format_exc())


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(f"Synthwave MIDI Reimaginer GUI v{APP_VERSION}")
        self.resize(1200, 820)
        self.last_result: dict | None = None
        self.worker_thread: QThread | None = None
        self.worker: QObject | None = None
        self._bpm_user_overridden = False
        self._updating_bpm_programmatically = False
        self._updating_seed_programmatically = False
        self._language = "en"
        self._translations = self._load_translations(self._language)
        self._styles = core.load_style_presets()
        self._theme_files = self._discover_themes()
        self._build_ui()
        self._apply_theme_by_id("dark")
        self._retranslate_ui()
        self._log(self._tr("log_ready"))

    # -----------------------------
    # Localization / theming
    # -----------------------------
    def _load_translations(self, lang: str) -> dict:
        path = LANG_DIR / f"{lang}.json"
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            if lang != "en":
                try:
                    return json.loads((LANG_DIR / "en.json").read_text(encoding="utf-8"))
                except Exception:
                    pass
        return {}

    def _tr(self, key: str, default: str | None = None) -> str:
        return str(self._translations.get(key, default if default is not None else key))

    def _style_text(self, style: dict, field: str, fallback_field: str | None = None) -> str:
        lang_field = f"{field}_{self._language}"
        if style.get(lang_field):
            return str(style.get(lang_field))
        if style.get(field):
            return str(style.get(field))
        if fallback_field and style.get(fallback_field):
            return str(style.get(fallback_field))
        return ""

    def _discover_themes(self) -> dict[str, Path]:
        themes: dict[str, Path] = {}
        if THEME_DIR.exists():
            for path in sorted(THEME_DIR.glob("*.qss"), key=lambda p: p.stem.casefold()):
                themes[path.stem] = path
        return themes

    def _theme_display_name(self, theme_id: str) -> str:
        names = {
            "dark": "Dark",
            "light": "Light",
            "matrix": "Matrix",
            "hell": "Hell",
            "retro_amber": "Retro Amber",
            "ocean": "Ocean",
        }
        return names.get(theme_id, theme_id.replace("_", " ").title())

    def _apply_theme_by_id(self, theme_id: str):
        path = self._theme_files.get(theme_id)
        if path and path.exists():
            try:
                self.setStyleSheet(path.read_text(encoding="utf-8"))
                return
            except Exception as exc:
                self._log(f"Theme load failed for {theme_id}: {exc}") if hasattr(self, "log_text") else None
        # Hard fallback so the GUI is still usable if theme files are missing.
        self.setStyleSheet("""
            QWidget { background: #11151c; color: #dbe6f1; font-size: 10.5pt; }
            QLabel#Title { font-size: 22pt; font-weight: 700; color: #f0f7ff; padding: 4px 0 10px 0; }
            QGroupBox { border: 1px solid #2b3545; border-radius: 12px; margin-top: 10px; padding: 12px; background: #151b24; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #9fc7ff; }
            QLineEdit, QTextEdit, QComboBox { background: #0c1016; border: 1px solid #2c3a4c; border-radius: 8px; padding: 7px; selection-background-color: #315d9d; }
            QPushButton { background: #26364a; border: 1px solid #3f5b7d; border-radius: 10px; padding: 9px 14px; font-weight: 600; }
            QPushButton:hover { background: #314969; }
            QTabWidget::pane { border: 1px solid #2b3545; border-radius: 10px; }
            QProgressBar { border: 1px solid #2c3a4c; border-radius: 8px; text-align: center; background: #0c1016; }
            QProgressBar::chunk { background: #4b8de8; border-radius: 7px; }
        """)

    def _selected_theme_id(self) -> str:
        return str(self.theme_combo.currentData() or "dark") if hasattr(self, "theme_combo") else "dark"

    def _theme_changed(self, *args):
        self._apply_theme_by_id(self._selected_theme_id())

    def _language_changed(self, *args):
        lang = str(self.language_combo.currentData() or "en")
        self._language = lang
        self._translations = self._load_translations(lang)
        self._retranslate_ui()
        self._update_style_combo_labels()
        self._update_style_info()

    # -----------------------------
    # UI creation
    # -----------------------------
    def _build_ui(self):
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.setCentralWidget(scroll)

        central = QWidget()
        scroll.setWidget(central)
        main = QVBoxLayout(central)
        main.setContentsMargins(16, 16, 16, 16)
        main.setSpacing(12)

        self.title_label = QLabel()
        self.title_label.setObjectName("Title")
        self.title_label.setToolTip("Creates a cleaned-up derivative version from a MIDI file using selectable modular style presets, with offline MIDI/WAV rendering.")
        main.addWidget(self.title_label)

        # Source/output section.
        self.file_group = QGroupBox()
        fg = QGridLayout(self.file_group)
        self.source_label = QLabel()
        self.output_label = QLabel()
        self.prefix_label = QLabel()
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Choose a .mid or .midi file...")
        self.output_edit = QLineEdit(str(ROOT_DIR / "output"))
        self.prefix_edit = QLineEdit("{source}_{style}_seed{seed}")
        self.browse_src_btn = QPushButton()
        self.browse_src_btn.clicked.connect(self.browse_source)
        self.browse_out_btn = QPushButton()
        self.browse_out_btn.clicked.connect(self.browse_output)
        fg.addWidget(self.source_label, 0, 0)
        fg.addWidget(self.source_edit, 0, 1)
        fg.addWidget(self.browse_src_btn, 0, 2)
        fg.addWidget(self.output_label, 1, 0)
        fg.addWidget(self.output_edit, 1, 1)
        fg.addWidget(self.browse_out_btn, 1, 2)
        fg.addWidget(self.prefix_label, 2, 0)
        fg.addWidget(self.prefix_edit, 2, 1, 1, 2)
        main.addWidget(self.file_group)

        # Style section.
        self.style_group = QGroupBox()
        sg = QGridLayout(self.style_group)
        self.style_label = QLabel()
        self.style_combo = QComboBox()
        self._populate_style_combo()
        synth_idx = self.style_combo.findData("synthwave")
        if synth_idx >= 0:
            self.style_combo.setCurrentIndex(synth_idx)
        self.random_style_cb = QCheckBox()
        self.style_info_label = QLabel("")
        self.style_info_label.setWordWrap(True)
        self.style_combo.currentIndexChanged.connect(self._style_changed)
        self.random_style_cb.toggled.connect(self._update_style_info)
        sg.addWidget(self.style_label, 0, 0)
        sg.addWidget(self.style_combo, 0, 1)
        sg.addWidget(self.random_style_cb, 0, 2)
        sg.addWidget(self.style_info_label, 1, 0, 1, 3)
        main.addWidget(self.style_group)

        # Render options section.
        self.render_group = QGroupBox()
        og = QGridLayout(self.render_group)
        self.render_audio_cb = QCheckBox()
        self.render_audio_cb.setChecked(True)
        self.render_mp3_cb = QCheckBox()
        self.render_mp3_cb.setChecked(True)
        self.harmony_lock_cb = QCheckBox()
        self.harmony_lock_cb.setChecked(True)
        self.auto_seed_cb = QCheckBox()
        self.auto_seed_cb.setChecked(True)
        self.seed_label = QLabel()
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(1, 2147483647)
        self.seed_spin.setValue(core.new_auto_seed())
        self.new_seed_btn = QPushButton()
        self.new_seed_btn.clicked.connect(self.new_manual_seed)
        self.seed_spin.valueChanged.connect(self._manual_seed_edited)
        self.auto_seed_cb.toggled.connect(self._auto_seed_toggled)
        self.sample_rate_label = QLabel()
        self.sample_rate = QComboBox()
        self.sample_rate.addItems(["22050", "32000", "44100", "48000", "96000", "128000"])
        self.sample_rate.setCurrentText("44100")
        self.intensity_name_label = QLabel()
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.intensity_slider.setRange(0, 100)
        self.intensity_slider.setValue(65)
        self.intensity_label = QLabel("65%")
        self.intensity_slider.valueChanged.connect(self._intensity_changed)
        self.bpm_name_label = QLabel()
        self.bpm_slider = QSlider(Qt.Orientation.Horizontal)
        self.bpm_slider.setRange(40, 220)
        self.bpm_slider.setValue(124)
        self.bpm_label = QLabel("124 BPM")
        self.bpm_slider.valueChanged.connect(self._bpm_changed)
        self.repetition_name_label = QLabel()
        self.repetition_slider = QSlider(Qt.Orientation.Horizontal)
        self.repetition_slider.setRange(0, 100)
        self.repetition_slider.setValue(45)
        self.repetition_label = QLabel("45%")
        self.repetition_slider.valueChanged.connect(self._repetition_changed)
        self.use_style_instruments_cb = QCheckBox()
        self.use_style_instruments_cb.setChecked(False)
        og.addWidget(self.render_audio_cb, 0, 0)
        og.addWidget(self.render_mp3_cb, 0, 1)
        og.addWidget(self.sample_rate_label, 0, 2)
        og.addWidget(self.sample_rate, 0, 3)
        og.addWidget(self.intensity_name_label, 1, 0)
        og.addWidget(self.intensity_slider, 1, 1, 1, 2)
        og.addWidget(self.intensity_label, 1, 3)
        og.addWidget(self.bpm_name_label, 2, 0)
        og.addWidget(self.bpm_slider, 2, 1, 1, 2)
        og.addWidget(self.bpm_label, 2, 3)
        og.addWidget(self.repetition_name_label, 3, 0)
        og.addWidget(self.repetition_slider, 3, 1, 1, 2)
        og.addWidget(self.repetition_label, 3, 3)
        og.addWidget(self.harmony_lock_cb, 4, 0, 1, 2)
        og.addWidget(self.auto_seed_cb, 4, 2, 1, 2)
        og.addWidget(self.use_style_instruments_cb, 5, 0, 1, 2)
        og.addWidget(self.seed_label, 5, 2)
        og.addWidget(self.seed_spin, 5, 3)
        og.addWidget(self.new_seed_btn, 5, 4)
        main.addWidget(self.render_group)

        # UI options section.
        self.ui_group = QGroupBox()
        uig = QGridLayout(self.ui_group)
        self.theme_label = QLabel()
        self.theme_combo = QComboBox()
        for theme_id in sorted(self._theme_files, key=lambda x: self._theme_display_name(x).casefold()):
            self.theme_combo.addItem(self._theme_display_name(theme_id), theme_id)
        if self.theme_combo.count() == 0:
            self.theme_combo.addItem("Dark", "dark")
        idx = self.theme_combo.findData("dark")
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        self.theme_combo.currentIndexChanged.connect(self._theme_changed)
        self.language_label = QLabel()
        self.language_combo = QComboBox()
        self.language_combo.addItem("English", "en")
        self.language_combo.addItem("Deutsch", "de")
        self.language_combo.currentIndexChanged.connect(self._language_changed)
        uig.addWidget(self.theme_label, 0, 0)
        uig.addWidget(self.theme_combo, 0, 1)
        uig.addWidget(self.language_label, 0, 2)
        uig.addWidget(self.language_combo, 0, 3)
        main.addWidget(self.ui_group)

        # Action buttons.
        buttons = QHBoxLayout()
        self.play_source_btn = QPushButton()
        self.play_source_btn.clicked.connect(self.play_source_midi)
        self.analyze_btn = QPushButton()
        self.analyze_btn.clicked.connect(self.analyze_current)
        self.render_btn = QPushButton()
        self.render_btn.clicked.connect(self.render_current)
        self.open_out_btn = QPushButton()
        self.open_out_btn.clicked.connect(self.open_output_folder)
        self.play_midi_btn = QPushButton()
        self.play_midi_btn.clicked.connect(self.play_last_midi)
        self.play_audio_btn = QPushButton()
        self.play_audio_btn.clicked.connect(self.play_last_audio)
        for b in [self.play_source_btn, self.analyze_btn, self.render_btn, self.open_out_btn, self.play_midi_btn, self.play_audio_btn]:
            buttons.addWidget(b)
        main.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        main.addWidget(self.progress)

        self.status_label = QLabel()
        main.addWidget(self.status_label)

        self.tabs = QTabWidget()
        self.analysis_text = QTextEdit()
        self.analysis_text.setReadOnly(True)
        self.analysis_text.setFont(QFont("Consolas", 10))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.help_text = QTextEdit()
        self.help_text.setReadOnly(True)
        self.tabs.addTab(self.analysis_text, "Analysis")
        self.tabs.addTab(self.log_text, "Log")
        self.tabs.addTab(self.help_text, "Help")
        main.addWidget(self.tabs, 1)

        self._update_style_info()

    def _populate_style_combo(self):
        self.style_combo.blockSignals(True)
        try:
            self.style_combo.clear()
            for style in self._styles:
                name = self._style_text(style, "name") or style.get("name") or style.get("id")
                label = f"{name}  [{style.get('id')}]"
                self.style_combo.addItem(label, style.get("id"))
        finally:
            self.style_combo.blockSignals(False)

    def _update_style_combo_labels(self):
        current = self._selected_style_id()
        self._populate_style_combo()
        idx = self.style_combo.findData(current)
        if idx >= 0:
            self.style_combo.setCurrentIndex(idx)

    def _retranslate_ui(self):
        self.setWindowTitle(self._tr("window_title", f"Synthwave MIDI Reimaginer GUI v{APP_VERSION}"))
        self.title_label.setText(self._tr("title", "Synthwave MIDI Reimaginer - Multi Style"))
        self.file_group.setTitle(self._tr("group_source", "1. Source / Output"))
        self.source_label.setText(self._tr("source_midi", "Source MIDI:"))
        self.output_label.setText(self._tr("output_folder", "Output folder:"))
        self.prefix_label.setText(self._tr("filename_prefix", "Filename prefix:"))
        self.browse_src_btn.setText(self._tr("browse_midi", "Browse MIDI..."))
        self.browse_out_btn.setText(self._tr("browse_output", "Output Folder..."))
        self.style_group.setTitle(self._tr("group_style", "2. Style Preset"))
        self.style_label.setText(self._tr("style", "Style:"))
        self.random_style_cb.setText(self._tr("random_style", "Random Style from seed"))
        self.render_group.setTitle(self._tr("group_render", "3. Render Options"))
        self.render_audio_cb.setText(self._tr("render_wav", "Render WAV with internal synth"))
        self.render_mp3_cb.setText(self._tr("render_mp3", "Also try MP3 export"))
        self.sample_rate_label.setText(self._tr("sample_rate", "Sample rate:"))
        self.intensity_name_label.setText(self._tr("transformation_intensity", "Transformation intensity:"))
        self.bpm_name_label.setText(self._tr("bpm", "BPM:"))
        self.repetition_name_label.setText(self._tr("repeated_note_amount", "Repeated note amount:"))
        self.harmony_lock_cb.setText(self._tr("harmony_lock", "Harmony lock / fix clashing notes"))
        self.auto_seed_cb.setText(self._tr("auto_seed", "New random seed each render"))
        self.use_style_instruments_cb.setText(self._tr("use_style_instruments", "Use style lead/melody instruments"))
        self.seed_label.setText(self._tr("seed", "Seed:"))
        self.new_seed_btn.setText(self._tr("new_seed", "New Seed"))
        self.ui_group.setTitle(self._tr("group_ui", "4. UI Options"))
        self.theme_label.setText(self._tr("theme", "Theme:"))
        self.language_label.setText(self._tr("language", "Language:"))
        self.play_source_btn.setText(self._tr("play_source", "Play Source MIDI"))
        self.analyze_btn.setText(self._tr("analyze", "Analyze MIDI"))
        self.render_btn.setText(self._tr("create", "Create New Version"))
        self.open_out_btn.setText(self._tr("open_output", "Open Output Folder"))
        self.play_midi_btn.setText(self._tr("play_midi_output", "Play MIDI Output"))
        self.play_audio_btn.setText(self._tr("play_audio_output", "Play WAV/MP3 Output"))
        self.status_label.setText(self._tr("status_ready", "Status: Ready"))
        self.tabs.setTabText(0, self._tr("tab_analysis", "Analysis"))
        self.tabs.setTabText(1, self._tr("tab_log", "Log"))
        self.tabs.setTabText(2, self._tr("tab_help", "Help"))
        self.help_text.setMarkdown(self._help_markdown())
        self._apply_tooltips()
        self._update_intensity_tooltip()
        self._update_bpm_tooltip()
        self._update_repetition_tooltip()

    def _apply_tooltips(self):
        self.source_edit.setToolTip(self._tr("tt_source", "The original MIDI file. The tool analyzes track roles such as bass, lead, arp, pad and drums."))
        self.output_edit.setToolTip(self._tr("tt_output", "Folder where the new MIDI, WAV, optional MP3, and analysis text are written."))
        self.prefix_edit.setToolTip(self._tr("tt_prefix", "Output filename prefix. Placeholders: {source}, {style}, {style_name}, {seed}, {source_hash}."))
        self.style_combo.setToolTip(self._tr("tt_style", "Selects the musical transformation style. Presets are loaded from app/styles/style_presets.json."))
        self.random_style_cb.setToolTip(self._tr("tt_random_style", "If ON, the style is selected deterministically from the render seed."))
        self.render_audio_cb.setToolTip(self._tr("tt_render_wav", "Renders audio without relying on your Windows wavetable or external MIDI synth."))
        self.render_mp3_cb.setToolTip(self._tr("tt_render_mp3", "Optional. Needs a real ffmpeg.exe. If unavailable, WAV export still succeeds."))
        self.harmony_lock_cb.setToolTip(self._tr("tt_harmony", "Default ON. Snaps copied lead/arp/pad material to compatible scale/chord tones."))
        self.auto_seed_cb.setToolTip(self._tr("tt_auto_seed", "Default ON. Every render gets a fresh seed. Turn off to reproduce a previous result."))
        self.seed_spin.setToolTip(self._tr("tt_seed", "Manual reproducible seed. Disable Auto Seed to use this exact value."))
        self.new_seed_btn.setToolTip(self._tr("tt_new_seed", "Generate a new manual seed number and switch Auto Seed off."))
        self.sample_rate.setToolTip(self._tr("tt_sample_rate", "WAV sample rate. 44100 is usually enough; 22050 is smaller/faster; 96000+ is high resolution and slower."))
        self.use_style_instruments_cb.setToolTip(self._tr("tt_style_instruments", "Default OFF. When enabled, lead/hook/pluck/echo tracks use the selected style's recommended GM instruments."))
        self.theme_combo.setToolTip(self._tr("tt_theme", "UI theme only. Theme files live in app/themes as .qss files."))
        self.language_combo.setToolTip(self._tr("tt_language", "Interface language. Language files live in app/lang as JSON files."))
        self.play_source_btn.setToolTip(self._tr("tt_play_source", "Open the selected source MIDI in your default MIDI player for comparison."))
        self.play_midi_btn.setToolTip(self._tr("tt_play_midi", "Open the last generated MIDI in your default MIDI player."))
        self.play_audio_btn.setToolTip(self._tr("tt_play_audio", "Open the last generated WAV or MP3 in your default audio player."))
        self.progress.setToolTip(self._tr("tt_progress", "Shows the current analysis/render stage. If it stalls, check the Log tab."))

    def _help_markdown(self) -> str:
        return self._tr("help_markdown", f"""
# Synthwave MIDI Reimaginer GUI v{APP_VERSION}

This tool analyzes a MIDI file and creates a cleaned-up derivative version using a selectable style preset.

## Important controls

- **Transformation Intensity** changes how strongly the song is rearranged.
- **BPM** controls tempo independently from transformation intensity.
- **Repeated note amount** controls how strongly long same-note repetitions are allowed.
- **Seed** controls reproducible variation. Auto Seed is ON by default.
- **Random Style from seed** chooses a style deterministically from the seed.
- **Play Source MIDI**, **Play MIDI Output**, and **Play WAV/MP3 Output** make comparison easier.

## Modular files

- Styles: `app/styles/style_presets.json`
- CSV overview: `app/styles/electronic_styles.csv`
- UI themes: `app/themes/*.qss`
- UI language files: `app/lang/*.json`
""")

    # -----------------------------
    # Style helpers / dynamic labels
    # -----------------------------
    def _selected_style_id(self) -> str:
        return str(self.style_combo.currentData() or "synthwave")

    def _style_by_id(self, style_id: str) -> dict:
        for style in getattr(self, "_styles", []):
            if style.get("id") == style_id:
                return style
        return core.get_style_by_id(style_id)

    def _style_changed(self, *args):
        self._update_style_info()

    def _update_style_info(self):
        style = self._style_by_id(self._selected_style_id())
        mode = self._tr("random_style_info_prefix", "Random ON: resolved style is chosen from the seed at render time. ") if getattr(self, "random_style_cb", None) and self.random_style_cb.isChecked() else ""
        info = self._style_text(style, "info") or str(style.get("info", ""))
        instruments = self._style_text(style, "instruments") or str(style.get("instruments", ""))
        self.style_info_label.setText(
            f"{mode}{info} | BPM {style.get('bpm_min', '?')}-{style.get('bpm_max', '?')} | "
            f"{self._tr('drums', 'Drums')}: {style.get('drum_feel', '?')} | "
            f"{self._tr('instruments', 'Instruments')}: {instruments}"
        )
        if hasattr(self, "bpm_slider") and not getattr(self, "_bpm_user_overridden", False):
            try:
                bpm = int(round((float(style.get("bpm_min", 100)) + float(style.get("bpm_max", 130))) / 2.0))
            except Exception:
                bpm = 124
            self._updating_bpm_programmatically = True
            try:
                self.bpm_slider.setValue(max(self.bpm_slider.minimum(), min(self.bpm_slider.maximum(), bpm)))
            finally:
                self._updating_bpm_programmatically = False
        self._update_intensity_tooltip()
        self._update_bpm_tooltip()
        self._update_repetition_tooltip()

    def _intensity_changed(self, value: int):
        self.intensity_label.setText(f"{value}%")
        self._update_intensity_tooltip()

    def _bpm_changed(self, value: int):
        self.bpm_label.setText(f"{value} BPM")
        if not getattr(self, "_updating_bpm_programmatically", False):
            self._bpm_user_overridden = True
        self._update_bpm_tooltip()

    def _repetition_changed(self, value: int):
        self.repetition_label.setText(f"{value}%")
        self._update_repetition_tooltip()

    def _update_bpm_tooltip(self):
        if not hasattr(self, "bpm_slider"):
            return
        style = self._style_by_id(self._selected_style_id())
        self.bpm_slider.setToolTip(
            self._tr("tt_bpm_dynamic", "Target tempo for the generated MIDI/WAV. Current: {value} BPM. Selected style range: {lo}-{hi} BPM.").format(
                value=self.bpm_slider.value(), lo=style.get("bpm_min", "?"), hi=style.get("bpm_max", "?")
            )
        )

    def _update_repetition_tooltip(self):
        if not hasattr(self, "repetition_slider"):
            return
        self.repetition_slider.setToolTip(
            self._tr("tt_repetition_dynamic", "Controls how much repeated same-note material is allowed. Current: {value}%. 0% reduces long loops, 100% preserves repetitive patterns.").format(
                value=self.repetition_slider.value()
            )
        )

    def _update_intensity_tooltip(self):
        if not hasattr(self, "intensity_slider"):
            return
        value = self.intensity_slider.value()
        if getattr(self, "random_style_cb", None) and self.random_style_cb.isChecked():
            style_name = self._tr("seed_resolved_random_style", "the seed-resolved random style")
            style_hint = self._tr("random_style_hint", "Random Style is ON, so the seed first chooses the style, then the same seed shapes the arrangement.")
        else:
            style = self._style_by_id(self._selected_style_id())
            style_name = self._style_text(style, "name") or str(style.get("name", self._selected_style_id()))
            style_hint = self._style_text(style, "info") or str(style.get("info", ""))
        self.intensity_slider.setToolTip(
            self._tr("tt_intensity_dynamic", "Transformation strength for {style}. Current: {value}%. 0% = close to source, 50% = recognizable but rearranged, 100% = largely regenerated in this style. {hint}").format(
                style=style_name, value=value, hint=style_hint
            )
        )

    # -----------------------------
    # File selection / settings
    # -----------------------------
    def browse_source(self):
        start = str(Path(self.source_edit.text()).parent) if self.source_edit.text() else str(ROOT_DIR)
        path, _ = QFileDialog.getOpenFileName(self, self._tr("choose_midi", "Choose MIDI file"), start, "MIDI files (*.mid *.midi);;All files (*.*)")
        if path:
            self.source_edit.setText(path)
            src = Path(path)
            self.output_edit.setText(str(src.parent / "reimagined_output"))
            self.prefix_edit.setText("{source}_{style}_seed{seed}")

    def browse_output(self):
        start = self.output_edit.text() or str(ROOT_DIR / "output")
        path = QFileDialog.getExistingDirectory(self, self._tr("choose_output", "Choose output folder"), start)
        if path:
            self.output_edit.setText(path)

    def _source_path(self) -> Path | None:
        path = Path(self.source_edit.text().strip().strip('"'))
        if not path.exists() or not path.is_file():
            QMessageBox.warning(self, self._tr("missing_midi_title", "Missing MIDI"), self._tr("missing_midi_msg", "Please choose an existing .mid or .midi file first."))
            return None
        return path

    def _settings(self) -> JobSettings | None:
        src = self._source_path()
        if not src:
            return None
        out = Path(self.output_edit.text().strip().strip('"') or (src.parent / "reimagined_output"))
        seed = core.new_auto_seed() if self.auto_seed_cb.isChecked() else int(self.seed_spin.value())
        if self.auto_seed_cb.isChecked():
            self._updating_seed_programmatically = True
            try:
                self.seed_spin.setValue(seed)
            finally:
                self._updating_seed_programmatically = False
        prefix = self.prefix_edit.text().strip() or "{source}_{style}_seed{seed}"
        return JobSettings(
            source=src,
            output_dir=out,
            prefix=prefix,
            render_audio=self.render_audio_cb.isChecked(),
            render_mp3=self.render_mp3_cb.isChecked(),
            sample_rate=int(self.sample_rate.currentText()),
            intensity=self.intensity_slider.value() / 100.0,
            target_bpm=float(self.bpm_slider.value()),
            repetition=self.repetition_slider.value() / 100.0,
            use_style_instruments=self.use_style_instruments_cb.isChecked(),
            harmony_lock=self.harmony_lock_cb.isChecked(),
            seed=seed,
            style_id=self._selected_style_id(),
            random_style=self.random_style_cb.isChecked(),
        )

    # -----------------------------
    # Logging / worker handling
    # -----------------------------
    def _log(self, text: str):
        self.log_text.append(text)
        self.log_text.ensureCursorVisible()

    def _worker_log(self, text: str):
        match = re.match(r"^\[(\d{1,3})%\]\s*(.*)$", text.strip())
        if match:
            pct = max(0, min(100, int(match.group(1))))
            msg = match.group(2).strip() or text.strip()
            self.progress.setRange(0, 100)
            self.progress.setValue(pct)
            self.status_label.setText(self._tr("status_pct", "Status: {pct}% - {msg}").format(pct=pct, msg=msg))
        else:
            self.status_label.setText(self._tr("status_text", "Status: {msg}").format(msg=text.strip()[:160]))
        self._log(text)

    def _set_busy(self, busy: bool):
        for w in [self.play_source_btn, self.analyze_btn, self.render_btn, self.open_out_btn, self.play_midi_btn, self.play_audio_btn]:
            w.setEnabled(not busy)
        self.progress.setRange(0, 100)
        if busy:
            self.progress.setValue(0)
            self.status_label.setText(self._tr("status_starting", "Status: Starting..."))
        else:
            self.progress.setValue(100)

    def analyze_current(self):
        src = self._source_path()
        if not src:
            return
        self._set_busy(True)
        self._log(self._tr("log_analyzing", "Analyzing {path} ...").format(path=src))
        self.worker_thread = QThread(self)
        worker = AnalyzeWorker(src)
        self.worker = worker
        worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(worker.run)
        worker.log.connect(self._worker_log)
        worker.finished.connect(self._analysis_done)
        worker.failed.connect(self._job_failed)
        worker.finished.connect(self.worker_thread.quit)
        worker.failed.connect(self.worker_thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def _analysis_done(self, analysis):
        self._set_busy(False)
        self.analysis_text.setPlainText(analysis.summary)
        self.status_label.setText(self._tr("status_analysis_finished", "Status: Analysis finished"))
        self._log(self._tr("analysis_finished", "Analysis finished."))
        self.worker = None

    def render_current(self):
        settings = self._settings()
        if not settings:
            return
        self._set_busy(True)
        self._log(
            self._tr("log_rendering", "Rendering new version from {name} with seed {seed}, style {style}{random}, BPM {bpm:.0f}, repetition {repetition:.2f} ...").format(
                name=settings.source.name,
                seed=settings.seed,
                style=settings.style_id,
                random=" (random)" if settings.random_style else "",
                bpm=settings.target_bpm,
                repetition=settings.repetition,
            )
        )
        self.worker_thread = QThread(self)
        worker = RenderWorker(settings)
        self.worker = worker
        worker.moveToThread(self.worker_thread)
        self.worker_thread.started.connect(worker.run)
        worker.log.connect(self._worker_log)
        worker.finished.connect(self._render_done)
        worker.failed.connect(self._job_failed)
        worker.finished.connect(self.worker_thread.quit)
        worker.failed.connect(self.worker_thread.quit)
        worker.finished.connect(worker.deleteLater)
        worker.failed.connect(worker.deleteLater)
        self.worker_thread.finished.connect(self.worker_thread.deleteLater)
        self.worker_thread.start()

    def _render_done(self, result):
        self._set_busy(False)
        self.last_result = result
        self.analysis_text.setPlainText(result.get("summary", ""))
        self.status_label.setText(self._tr("status_render_finished", "Status: Render finished"))
        self._log(self._tr("done", "Done."))
        self.worker = None
        files = "\n".join(f"{k.upper()}: {v}" for k, v in result.items() if k != "summary" and v)
        QMessageBox.information(self, self._tr("render_finished_title", "Render finished"), self._tr("render_finished_msg", "Created files:\n\n{files}").format(files=files))

    def _job_failed(self, error: str):
        self._set_busy(False)
        self.status_label.setText(self._tr("status_error", "Status: Error"))
        self._log(f"ERROR: {error}")
        self.worker = None
        QMessageBox.critical(self, self._tr("error", "Error"), error)

    # -----------------------------
    # Seed and playback actions
    # -----------------------------
    def _auto_seed_toggled(self, checked: bool):
        if checked:
            self.status_label.setText(self._tr("status_auto_seed", "Status: Auto Seed ON - a fresh seed will be chosen on each render"))
        else:
            self.status_label.setText(self._tr("status_manual_seed", "Status: Manual Seed ON - next render uses seed {seed}").format(seed=self.seed_spin.value()))

    def _manual_seed_edited(self, value: int):
        if getattr(self, "_updating_seed_programmatically", False):
            return
        if self.auto_seed_cb.isChecked():
            self.auto_seed_cb.blockSignals(True)
            self.auto_seed_cb.setChecked(False)
            self.auto_seed_cb.blockSignals(False)
            self.status_label.setText(self._tr("status_manual_seed", "Status: Manual Seed ON - next render uses seed {seed}").format(seed=value))

    def new_manual_seed(self):
        self._updating_seed_programmatically = True
        try:
            seed = core.new_auto_seed()
            self.seed_spin.setValue(seed)
        finally:
            self._updating_seed_programmatically = False
        if self.auto_seed_cb.isChecked():
            self.auto_seed_cb.setChecked(False)
        self.status_label.setText(self._tr("status_manual_seed", "Status: Manual Seed ON - next render uses seed {seed}").format(seed=self.seed_spin.value()))
        self._log(self._tr("log_manual_seed", "Manual seed selected: {seed}").format(seed=self.seed_spin.value()))

    def open_output_folder(self):
        folder = Path(self.output_edit.text().strip().strip('"') or (ROOT_DIR / "output"))
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def play_source_midi(self):
        src = self._source_path()
        if src:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(src)))

    def play_last_midi(self):
        if not self.last_result:
            QMessageBox.information(self, self._tr("no_render_title", "No render yet"), self._tr("no_midi_msg", "No rendered MIDI is available yet."))
            return
        path = self.last_result.get("midi") or self.last_result.get("mid")
        if path and Path(path).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(path))
            return
        QMessageBox.information(self, self._tr("no_midi_title", "No MIDI"), self._tr("last_no_midi_msg", "The last job did not create a MIDI file."))

    def play_last_audio(self):
        if not self.last_result:
            QMessageBox.information(self, self._tr("no_render_title", "No render yet"), self._tr("no_audio_msg", "No rendered audio is available yet."))
            return
        for key in ("mp3", "wav"):
            path = self.last_result.get(key)
            if path and Path(path).exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
                return
        QMessageBox.information(self, self._tr("no_audio_title", "No audio"), self._tr("last_no_audio_msg", "The last job did not create a WAV or MP3 file."))


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Synthwave MIDI Reimaginer")
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
