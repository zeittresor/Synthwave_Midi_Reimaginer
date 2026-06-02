#!/usr/bin/env python3
"""
PyQt6 GUI for Synthwave MIDI Reimaginer.
"""
from __future__ import annotations

import os
import sys
import subprocess
import traceback
import re
from pathlib import Path
from dataclasses import dataclass

from PyQt6.QtCore import QObject, QThread, pyqtSignal, Qt
from PyQt6.QtGui import QFont, QDesktopServices
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QFileDialog, QMessageBox, QVBoxLayout, QHBoxLayout,
    QGridLayout, QPushButton, QLabel, QLineEdit, QTextEdit, QCheckBox, QComboBox, QSlider,
    QProgressBar, QGroupBox, QSpinBox, QTabWidget
)
from PyQt6.QtCore import QUrl

# Allow running directly from app folder or project root.
APP_DIR = Path(__file__).resolve().parent
ROOT_DIR = APP_DIR.parent
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import midi_reimaginer_core as core

APP_VERSION = "0.2.3"


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
        self.setWindowTitle(f"Synthwave MIDI Reimaginer GUI v{APP_VERSION} - Multi Style")
        self.resize(1180, 780)
        self.last_result: dict | None = None
        self.worker_thread: QThread | None = None
        self.worker: QObject | None = None
        self._bpm_user_overridden = False
        self._updating_bpm_programmatically = False
        self._build_ui()
        self._apply_dark_theme()
        self._log("Ready. Select a MIDI file, analyze it, then render a new version.")

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main = QVBoxLayout(central)
        main.setContentsMargins(16, 16, 16, 16)
        main.setSpacing(12)

        title = QLabel("Synthwave MIDI Reimaginer - Multi Style")
        title.setObjectName("Title")
        title.setToolTip("Creates a cleaned-up derivative electronic version from a MIDI file using selectable modular style presets, with offline MIDI/WAV rendering.")
        main.addWidget(title)

        file_group = QGroupBox("1. Source / Output")
        fg = QGridLayout(file_group)
        self.source_edit = QLineEdit()
        self.source_edit.setPlaceholderText("Choose a .mid or .midi file...")
        self.source_edit.setToolTip("The original MIDI file. The tool analyzes track roles such as bass, lead, arp, pad and drums.")
        self.output_edit = QLineEdit(str(ROOT_DIR / "output"))
        self.output_edit.setToolTip("Folder where the new MIDI, WAV, optional MP3, and analysis text are written.")
        self.prefix_edit = QLineEdit("{source}_{style}_seed{seed}")
        self.prefix_edit.setToolTip("Output filename prefix. Placeholders: {source}, {style}, {style_name}, {seed}, {source_hash}. Keeping {seed} and {style} prevents accidental overwrites and makes versions reproducible.")
        browse_src = QPushButton("Browse MIDI...")
        browse_src.clicked.connect(self.browse_source)
        browse_out = QPushButton("Output Folder...")
        browse_out.clicked.connect(self.browse_output)
        fg.addWidget(QLabel("Source MIDI:"), 0, 0)
        fg.addWidget(self.source_edit, 0, 1)
        fg.addWidget(browse_src, 0, 2)
        fg.addWidget(QLabel("Output folder:"), 1, 0)
        fg.addWidget(self.output_edit, 1, 1)
        fg.addWidget(browse_out, 1, 2)
        fg.addWidget(QLabel("Filename prefix:"), 2, 0)
        fg.addWidget(self.prefix_edit, 2, 1, 1, 2)
        main.addWidget(file_group)

        style_group = QGroupBox("2. Style Preset")
        sg = QGridLayout(style_group)
        self.style_combo = QComboBox()
        self._styles = core.load_style_presets()
        for style in self._styles:
            label = f"{style.get('name', style.get('id'))}  [{style.get('id')}]"
            self.style_combo.addItem(label, style.get("id"))
        synth_idx = self.style_combo.findData("synthwave")
        if synth_idx >= 0:
            self.style_combo.setCurrentIndex(synth_idx)
        self.style_combo.setToolTip("Selects the musical transformation style. Presets are loaded from app/styles/style_presets.json, so the feature is modular and expandable.")
        self.random_style_cb = QCheckBox("Random Style from seed")
        self.random_style_cb.setToolTip("If ON, the style is selected deterministically from the render seed. Same seed + same source + same style table reproduces the same resolved style.")
        self.style_info_label = QLabel("")
        self.style_info_label.setWordWrap(True)
        self.style_info_label.setToolTip("Brief info from the selected style preset.")
        self.style_combo.currentIndexChanged.connect(self._update_style_info)
        self.random_style_cb.toggled.connect(self._update_style_info)
        sg.addWidget(QLabel("Style:"), 0, 0)
        sg.addWidget(self.style_combo, 0, 1)
        sg.addWidget(self.random_style_cb, 0, 2)
        sg.addWidget(self.style_info_label, 1, 0, 1, 3)
        main.addWidget(style_group)
        self._update_style_info()

        options_group = QGroupBox("3. Render Options")
        og = QGridLayout(options_group)
        self.render_audio_cb = QCheckBox("Render WAV with internal synth")
        self.render_audio_cb.setChecked(True)
        self.render_audio_cb.setToolTip("Renders audio without relying on your Windows wavetable or external MIDI synth.")
        self.render_mp3_cb = QCheckBox("Also try MP3 export")
        self.render_mp3_cb.setChecked(True)
        self.render_mp3_cb.setToolTip("Optional. Needs a real ffmpeg.exe. If unavailable, WAV export still succeeds.")
        self.harmony_lock_cb = QCheckBox("Harmony lock / fix clashing notes")
        self.harmony_lock_cb.setChecked(True)
        self.harmony_lock_cb.setToolTip("Default ON. Detects a likely key/scale and snaps copied lead/arp/pad material to compatible scale/chord tones so tracks do not fight each other.")
        self.auto_seed_cb = QCheckBox("New random seed each render")
        self.auto_seed_cb.setChecked(True)
        self.auto_seed_cb.setToolTip("Default ON. Every render gets a fresh seed, but the exact seed is written into the analysis TXT and filename. Turn this off to reproduce a previous result.")
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(1, 2147483647)
        self.seed_spin.setValue(core.new_auto_seed())
        self.seed_spin.setToolTip("Manual reproducible seed. Disable 'New random seed each render' to use this value exactly.")
        self.new_seed_btn = QPushButton("New Seed")
        self.new_seed_btn.setToolTip("Generate a new manual seed number. This also switches Auto Seed off so the shown seed is used reproducibly on the next render.")
        self.new_seed_btn.clicked.connect(self.new_manual_seed)
        self.seed_spin.valueChanged.connect(self._manual_seed_edited)
        self.auto_seed_cb.toggled.connect(self._auto_seed_toggled)
        # Important UX fix v0.1.5:
        # The seed field and New Seed button stay interactive even when Auto Seed is ON.
        # Auto Seed means "pick a fresh seed at render time", not "lock the controls".
        self.seed_spin.setEnabled(True)
        self.new_seed_btn.setEnabled(True)
        self._updating_seed_programmatically = False
        self.sample_rate = QComboBox()
        self.sample_rate.addItems(["44100", "48000"])
        self.sample_rate.setToolTip("WAV sample rate. 44100 is usually enough and faster.")
        self.intensity_slider = QSlider(Qt.Orientation.Horizontal)
        self.intensity_slider.setRange(0, 100)
        self.intensity_slider.setValue(65)
        self.intensity_slider.setToolTip("Transformation strength. 0% = close to the source/cleanup only. 100% = mostly regenerated song in the selected style.")
        self.intensity_label = QLabel("65%")
        self.intensity_slider.valueChanged.connect(self._intensity_changed)

        self.bpm_slider = QSlider(Qt.Orientation.Horizontal)
        self.bpm_slider.setRange(40, 220)
        self.bpm_slider.setValue(124)
        self.bpm_label = QLabel("124 BPM")
        self.bpm_slider.valueChanged.connect(self._bpm_changed)

        self.repetition_slider = QSlider(Qt.Orientation.Horizontal)
        self.repetition_slider.setRange(0, 100)
        self.repetition_slider.setValue(45)
        self.repetition_label = QLabel("45%")
        self.repetition_slider.valueChanged.connect(self._repetition_changed)

        self.use_style_instruments_cb = QCheckBox("Use style lead/melody instruments")
        self.use_style_instruments_cb.setChecked(False)
        self.use_style_instruments_cb.setToolTip("Default OFF. When enabled, generated lead/hook/pluck/echo tracks use the selected style's recommended General MIDI instruments. When off, the arrangement changes but melody colors stay in a stable synth-friendly set.")

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["Dark", "Light"])
        self.theme_combo.currentTextChanged.connect(lambda t: self._apply_dark_theme() if t == "Dark" else self._apply_light_theme())
        self.theme_combo.setToolTip("UI theme only. Does not change audio rendering.")
        og.addWidget(self.render_audio_cb, 0, 0)
        og.addWidget(self.render_mp3_cb, 0, 1)
        og.addWidget(QLabel("Sample rate:"), 0, 2)
        og.addWidget(self.sample_rate, 0, 3)
        og.addWidget(QLabel("Transformation intensity:"), 1, 0)
        og.addWidget(self.intensity_slider, 1, 1, 1, 2)
        og.addWidget(self.intensity_label, 1, 3)
        og.addWidget(QLabel("BPM:"), 2, 0)
        og.addWidget(self.bpm_slider, 2, 1, 1, 2)
        og.addWidget(self.bpm_label, 2, 3)
        og.addWidget(QLabel("Repeated note amount:"), 3, 0)
        og.addWidget(self.repetition_slider, 3, 1, 1, 2)
        og.addWidget(self.repetition_label, 3, 3)
        og.addWidget(self.harmony_lock_cb, 4, 0, 1, 2)
        og.addWidget(self.auto_seed_cb, 4, 2, 1, 2)
        og.addWidget(self.use_style_instruments_cb, 5, 0, 1, 2)
        og.addWidget(QLabel("Seed:"), 5, 2)
        og.addWidget(self.seed_spin, 5, 3)
        og.addWidget(self.new_seed_btn, 5, 4)
        og.addWidget(QLabel("Theme:"), 6, 0)
        og.addWidget(self.theme_combo, 6, 1)
        main.addWidget(options_group)
        self._update_style_info()

        buttons = QHBoxLayout()
        self.analyze_btn = QPushButton("Analyze MIDI")
        self.analyze_btn.setToolTip("Reads the MIDI and shows track role detection before rendering.")
        self.analyze_btn.clicked.connect(self.analyze_current)
        self.render_btn = QPushButton("Create New Version")
        self.render_btn.setToolTip("Creates a new MIDI and optionally renders WAV/MP3.")
        self.render_btn.clicked.connect(self.render_current)
        self.open_out_btn = QPushButton("Open Output Folder")
        self.open_out_btn.clicked.connect(self.open_output_folder)
        self.play_wav_btn = QPushButton("Play Last WAV/MP3")
        self.play_wav_btn.setToolTip("Opens the last rendered WAV or MP3 in your default player.")
        self.play_wav_btn.clicked.connect(self.play_last_audio)
        for b in [self.analyze_btn, self.render_btn, self.open_out_btn, self.play_wav_btn]:
            buttons.addWidget(b)
        main.addLayout(buttons)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setToolTip("Shows the current analysis/render stage. If it stays at one step for a long time, the log tells you where.")
        main.addWidget(self.progress)

        self.status_label = QLabel("Status: Ready")
        self.status_label.setToolTip("Current stage of the active job.")
        main.addWidget(self.status_label)

        tabs = QTabWidget()
        self.analysis_text = QTextEdit()
        self.analysis_text.setReadOnly(True)
        self.analysis_text.setFont(QFont("Consolas", 10))
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setFont(QFont("Consolas", 10))
        self.help_text = QTextEdit()
        self.help_text.setReadOnly(True)
        self.help_text.setMarkdown(self._help_markdown())
        tabs.addTab(self.analysis_text, "Analysis")
        tabs.addTab(self.log_text, "Log")
        tabs.addTab(self.help_text, "Help")
        main.addWidget(tabs, 1)

    def _help_markdown(self) -> str:
        return f"""
# Synthwave MIDI Reimaginer GUI v{APP_VERSION}

This tool analyzes a MIDI file and creates a cleaned-up derivative electronic version using a selectable style preset.

## What it does

- Detects likely **bass**, **lead/hook**, **arp/pluck**, **pad/chord source**, **drums**, and overly high/problematic tracks.
- Lets you choose a modular **Style Preset** such as Synthwave, Darksynth, Techno, Drum and Bass, Ambient, Chiptune, etc.
- Optional **Random Style from seed** mode picks a style reproducibly from the seed.
- Three main musical sliders: **Transformation Intensity**, **BPM**, and **Repeated note amount**.
- Optional **Use style lead/melody instruments** applies the selected preset's GM programs to hook/lead/pluck/echo tracks.
- Quantizes musical parts to a cleaner grid.
- Detects a likely key/scale and, with **Harmony lock**, snaps copied notes to compatible scale/chord tones.
- Uses a reproducible **seed**. Auto mode is ON by default and chooses a new seed for every render; manual mode repeats the same version exactly.
- Moves squeaky high hook material into a more usable mid-range.
- Adds warm pad support, grid-locked synthwave drums, and a deterministic internal audio preview render.

## Offline behavior

After `install_windows.bat` has installed the virtual environment once, `run_windows.bat` works offline. For fully offline reinstall on another machine, use `prepare_wheelhouse_online.bat` once on an internet-connected machine and keep the generated `wheelhouse` folder.

## MP3 export

MP3 export requires a **real ffmpeg binary**. The tool validates `ffmpeg -version` and ignores fake Python shims such as some `ffmpeg.EXE` files in Python Scripts folders. If MP3 fails, WAV and MIDI are still created.

## Output files

- `.mid` new MIDI arrangement
- `.wav` internal synth preview
- `.mp3` optional ffmpeg conversion
- `_analysis.txt` text report of the detected MIDI structure, seed, source hash, BPM, repetition amount, requested style and resolved style

## Modular style files

The selectable styles live in `app/styles/style_presets.json`. A human-readable overview is also included as `app/styles/electronic_styles.csv`. You can add styles later by copying one JSON object and changing the id/values.
"""

    def _apply_dark_theme(self):
        self.setStyleSheet("""
            QWidget { background: #11151c; color: #dbe6f1; font-size: 10.5pt; }
            QLabel#Title { font-size: 22pt; font-weight: 700; color: #f0f7ff; padding: 4px 0 10px 0; }
            QGroupBox { border: 1px solid #2b3545; border-radius: 12px; margin-top: 10px; padding: 12px; background: #151b24; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #9fc7ff; }
            QLineEdit, QTextEdit, QComboBox { background: #0c1016; border: 1px solid #2c3a4c; border-radius: 8px; padding: 7px; selection-background-color: #315d9d; }
            QPushButton { background: #26364a; border: 1px solid #3f5b7d; border-radius: 10px; padding: 9px 14px; font-weight: 600; }
            QPushButton:hover { background: #314969; }
            QPushButton:pressed { background: #1f2b3a; }
            QCheckBox { spacing: 8px; }
            QTabWidget::pane { border: 1px solid #2b3545; border-radius: 10px; }
            QTabBar::tab { background: #151b24; padding: 9px 16px; border: 1px solid #2b3545; border-top-left-radius: 8px; border-top-right-radius: 8px; }
            QTabBar::tab:selected { background: #26364a; color: #ffffff; }
            QProgressBar { border: 1px solid #2c3a4c; border-radius: 8px; text-align: center; background: #0c1016; }
            QProgressBar::chunk { background: #4b8de8; border-radius: 7px; }
            QSlider::groove:horizontal { height: 6px; background: #2c3a4c; border-radius: 3px; }
            QSlider::handle:horizontal { background: #8fc1ff; width: 18px; margin: -6px 0; border-radius: 9px; }
        """)

    def _apply_light_theme(self):
        self.setStyleSheet("""
            QWidget { background: #f4f6fb; color: #18202b; font-size: 10.5pt; }
            QLabel#Title { font-size: 22pt; font-weight: 700; color: #111927; padding: 4px 0 10px 0; }
            QGroupBox { border: 1px solid #c8d2e0; border-radius: 12px; margin-top: 10px; padding: 12px; background: #ffffff; }
            QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #245c9d; }
            QLineEdit, QTextEdit, QComboBox { background: #ffffff; border: 1px solid #bac7d8; border-radius: 8px; padding: 7px; selection-background-color: #9ec8ff; }
            QPushButton { background: #e4edf9; border: 1px solid #abc4e2; border-radius: 10px; padding: 9px 14px; font-weight: 600; }
            QPushButton:hover { background: #d2e5fb; }
            QPushButton:pressed { background: #bfd5ee; }
            QTabWidget::pane { border: 1px solid #c8d2e0; border-radius: 10px; }
            QTabBar::tab { background: #e9eef6; padding: 9px 16px; border: 1px solid #c8d2e0; border-top-left-radius: 8px; border-top-right-radius: 8px; }
            QTabBar::tab:selected { background: #ffffff; color: #111927; }
            QProgressBar { border: 1px solid #bac7d8; border-radius: 8px; text-align: center; background: #ffffff; }
            QProgressBar::chunk { background: #4b8de8; border-radius: 7px; }
        """)

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
            self.status_label.setText(f"Status: {pct}% - {msg}")
        else:
            self.status_label.setText(f"Status: {text.strip()[:160]}")
        self._log(text)

    def _selected_style_id(self) -> str:
        return str(self.style_combo.currentData() or "synthwave")

    def _style_by_id(self, style_id: str) -> dict:
        for style in getattr(self, "_styles", []):
            if style.get("id") == style_id:
                return style
        return core.get_style_by_id(style_id)

    def _update_style_info(self):
        style = self._style_by_id(self._selected_style_id())
        mode = "Random ON: resolved style is chosen from the seed at render time. " if getattr(self, "random_style_cb", None) and self.random_style_cb.isChecked() else ""
        self.style_info_label.setText(
            f"{mode}{style.get('info', '')} | BPM {style.get('bpm_min', '?')}-{style.get('bpm_max', '?')} | "
            f"Drums: {style.get('drum_feel', '?')} | Instruments: {style.get('instruments', '')}"
        )
        # Before the user touches BPM, style changes move the BPM slider to the
        # center of the preset's useful range. After manual movement, respect it.
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
            f"Target tempo for the generated MIDI/WAV. Current: {self.bpm_slider.value()} BPM.\n"
            f"Selected style range: {style.get('bpm_min', '?')}-{style.get('bpm_max', '?')} BPM.\n"
            "The slider is written into the analysis TXT and is part of reproducible generation settings."
        )

    def _update_repetition_tooltip(self):
        if not hasattr(self, "repetition_slider"):
            return
        value = self.repetition_slider.value()
        self.repetition_slider.setToolTip(
            f"Controls how much repeated same-note material is allowed. Current: {value}%.\n"
            "0% = aggressively reduce long monotone same-note loops by skipping or changing repeated notes.\n"
            "50% = balanced; some motif repetition remains, annoying loops are softened.\n"
            "100% = preserve/allow repetitive patterns, useful for techno, trance, minimal, chiptune, etc."
        )

    def _update_intensity_tooltip(self):
        if not hasattr(self, "intensity_slider"):
            return
        value = self.intensity_slider.value() if hasattr(self, "intensity_slider") else 65
        if getattr(self, "random_style_cb", None) and self.random_style_cb.isChecked():
            style_name = "the seed-resolved random style"
            style_hint = "Random Style is ON, so the seed first chooses the style, then the same seed shapes the arrangement."
        else:
            style = self._style_by_id(self._selected_style_id())
            style_name = str(style.get("name", self._selected_style_id()))
            style_hint = str(style.get("info", ""))
        self.intensity_slider.setToolTip(
            f"Transformation strength for {style_name}. Current: {value}%.\n"
            "0% = very close to the source MIDI: mostly cleanup, quantizing and harmonic safety.\n"
            "50% = recognizable source material with a stronger style arrangement.\n"
            f"100% = largely regenerated song in {style_name}, still using source key/structure as a guide.\n"
            f"{style_hint}"
        )

    def browse_source(self):
        start = str(Path(self.source_edit.text()).parent) if self.source_edit.text() else str(ROOT_DIR)
        path, _ = QFileDialog.getOpenFileName(self, "Choose MIDI file", start, "MIDI files (*.mid *.midi);;All files (*.*)")
        if path:
            self.source_edit.setText(path)
            src = Path(path)
            self.output_edit.setText(str(src.parent / "reimagined_output"))
            self.prefix_edit.setText("{source}_{style}_seed{seed}")

    def browse_output(self):
        start = self.output_edit.text() or str(ROOT_DIR / "output")
        path = QFileDialog.getExistingDirectory(self, "Choose output folder", start)
        if path:
            self.output_edit.setText(path)

    def _source_path(self) -> Path | None:
        path = Path(self.source_edit.text().strip().strip('"'))
        if not path.exists() or not path.is_file():
            QMessageBox.warning(self, "Missing MIDI", "Please choose an existing .mid or .midi file first.")
            return None
        return path

    def _set_busy(self, busy: bool):
        for w in [self.analyze_btn, self.render_btn, self.open_out_btn, self.play_wav_btn]:
            w.setEnabled(not busy)
        self.progress.setRange(0, 100)
        if busy:
            self.progress.setValue(0)
            self.status_label.setText("Status: Starting...")
        else:
            self.progress.setValue(100)

    def analyze_current(self):
        src = self._source_path()
        if not src:
            return
        self._set_busy(True)
        self._log(f"Analyzing {src} ...")
        self.worker_thread = QThread(self)
        worker = AnalyzeWorker(src)
        self.worker = worker  # keep a strong Python reference; otherwise PyQt may garbage-collect the worker while the thread is still running
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
        self.status_label.setText("Status: Analysis finished")
        self._log("Analysis finished.")
        self.worker = None

    def _auto_seed_toggled(self, checked: bool):
        if checked:
            self.status_label.setText("Status: Auto Seed ON - a fresh seed will be chosen on each render")
        else:
            self.status_label.setText(f"Status: Manual Seed ON - next render uses seed {self.seed_spin.value()}")

    def _manual_seed_edited(self, value: int):
        if getattr(self, "_updating_seed_programmatically", False):
            return
        # Editing the seed means the user wants reproducibility with that exact value.
        if self.auto_seed_cb.isChecked():
            self.auto_seed_cb.blockSignals(True)
            self.auto_seed_cb.setChecked(False)
            self.auto_seed_cb.blockSignals(False)
            self.status_label.setText(f"Status: Manual Seed ON - next render uses seed {value}")

    def new_manual_seed(self):
        self._updating_seed_programmatically = True
        try:
            seed = core.new_auto_seed()
            self.seed_spin.setValue(seed)
        finally:
            self._updating_seed_programmatically = False
        if self.auto_seed_cb.isChecked():
            self.auto_seed_cb.setChecked(False)
        self.status_label.setText(f"Status: Manual Seed ON - next render uses seed {self.seed_spin.value()}")
        self._log(f"Manual seed selected: {self.seed_spin.value()}")

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

    def render_current(self):
        settings = self._settings()
        if not settings:
            return
        self._set_busy(True)
        self._log(f"Rendering new version from {settings.source.name} with seed {settings.seed}, style {settings.style_id}{' (random)' if settings.random_style else ''}, BPM {settings.target_bpm:.0f}, repetition {settings.repetition:.2f} ...")
        self.worker_thread = QThread(self)
        worker = RenderWorker(settings)
        self.worker = worker  # keep a strong Python reference while the thread is running
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
        self.status_label.setText("Status: Render finished")
        self._log("Done.")
        self.worker = None
        files = "\n".join(f"{k.upper()}: {v}" for k, v in result.items() if k != "summary" and v)
        QMessageBox.information(self, "Render finished", f"Created files:\n\n{files}")

    def _job_failed(self, error: str):
        self._set_busy(False)
        self.status_label.setText("Status: Error")
        self._log(f"ERROR: {error}")
        self.worker = None
        QMessageBox.critical(self, "Error", error)

    def open_output_folder(self):
        folder = Path(self.output_edit.text().strip().strip('"') or (ROOT_DIR / "output"))
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def play_last_audio(self):
        if not self.last_result:
            QMessageBox.information(self, "No render yet", "No rendered audio is available yet.")
            return
        for key in ("mp3", "wav"):
            path = self.last_result.get(key)
            if path and Path(path).exists():
                QDesktopServices.openUrl(QUrl.fromLocalFile(path))
                return
        QMessageBox.information(self, "No audio", "The last job did not create a WAV or MP3 file.")


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("Synthwave MIDI Reimaginer")
    w = MainWindow()
    w.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
