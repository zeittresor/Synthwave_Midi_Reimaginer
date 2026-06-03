# Synthwave MIDI Reimaginer GUI v0.2.9

Offline-friendly PyQt6 GUI for analyzing MIDI files and creating derivative reimagined versions with selectable modular style presets.

Source hint for standalone copies:
`https://github.com/zeittresor/Synthwave_Midi_Reimaginer`

## New in v0.2.9

- Added **Keep source track volumes**. When enabled, generated replacement tracks keep closer to the original MIDI role/track loudness balance, even if instruments are changed.
- The source MIDI analysis now reports average velocity and estimated source volume per track.
- Render analysis TXT writes whether source-volume preservation was enabled.
- CLI supports `--preserve-source-volumes`.
- Includes the feedback learning, PyInstaller compile script, Source MIDI button placement, modular changelog folder, neutral bundled example MIDI, and standalone source comments from v0.2.8.

## New in v0.2.8

- Added local listener feedback / preference learning.
- After rendering a result, use **👍 Like Last** or **👎 Dislike Last** to rate it.
- Future renders can gently bias settings toward liked results and away from disliked patterns.
- Feedback is stored locally in `app_data/feedback/ratings.json`.
- Added **Reset Feedback** to clear the learning profile.
- Moved **Play Source MIDI** into the Source / Output section, so the bottom action row stays focused on main workflow actions.
- Added `compile_windows_pyinstaller.bat` to build a Windows EXE folder with PyInstaller.
- Improved PyInstaller runtime paths so bundled styles, themes and language files load correctly, while feedback remains writable next to the EXE.
- Kept changelogs in `docs/changelog/` instead of the project root.

## New in v0.2.7

- Reworked the former **Repeated note amount** control into **Accompaniment relaxation**.
- Moving the slider right now reduces fast repeated accompaniment attacks and creates more breathing room.
- High relaxation values add long harmony-safe pad/string relief layers instead of endless pluck/tick repetitions.
- Dense source-derived arp, glass support and tonal tick tracks are now thinned by the relaxation value.
- The analysis TXT now writes `Accompaniment relaxation` so generated files are easier to diagnose.

## New in v0.2.6

- Expanded style preset library with additional house, grime, hardcore, DnB, rave, rock and experimental styles.
- Presets are alphabetically sorted and remain editable through `app/styles/style_presets.json`.

## New in v0.2.5

- Added more style presets: Amapiano, Cumbia, Ragga, Electro Swing, UK Bass, UKG, Two Step, Acid Jazz, Rare Groove, Balearic and more.
- Added **Play Source MIDI** for direct comparison with the selected input file.
- Split output playback into **Play MIDI Output** and **Play WAV/MP3 Output**.
- Expanded WAV sample rates: 22050, 32000, 44100, 48000, 96000, 128000 Hz.
- GUI uses a vertical scroll area, so controls should not be cut off on smaller screens.
- Themes are external `.qss` files in `app/themes/`.
- Language files are external JSON files in `app/lang/`.

## Core controls

- **Style** selects the target arrangement/style preset.
- **Random Style from seed** chooses a style deterministically from the seed.
- **Transformation Intensity** controls how strongly the song is rearranged.
- **BPM** controls tempo independently from transformation intensity.
- **Accompaniment relaxation** controls whether fast accompaniment keeps pulsing or is thinned into breathing room with pads/strings.
- **Harmony lock** snaps copied lead/arp/pad material to compatible scale/chord tones.
- **Use style lead/melody instruments** optionally replaces lead/hook/pluck/echo instruments with style-appropriate instruments.
- **Keep source track volumes** keeps the generated mix closer to the original MIDI balance.
- **New random seed each render** is enabled by default; disable it to reproduce a specific seed.
- **Listener Feedback / Learning** stores local thumbs-up/down ratings and gently biases future renders.

## Build EXE on Windows

Run:

```bat
compile_windows_pyinstaller.bat
```

The script builds an onedir EXE package at:

```text
dist\SynthwaveMidiReimaginerGUI\SynthwaveMidiReimaginerGUI.exe
```

The onedir layout is intentional: it keeps modular styles, themes and languages bundled safely and keeps the feedback profile writable under `app_data/feedback/ratings.json` next to the EXE.

## Modular files

- Styles: `app/styles/style_presets.json`
- CSV overview: `app/styles/electronic_styles.csv`
- UI themes: `app/themes/*.qss`
- UI language files: `app/lang/*.json`
- Feedback profile: `app_data/feedback/ratings.json`
- Changelogs: `docs/changelog/`

## Running from source

Run `install_windows.bat`, then `run_windows.bat`.

For offline reuse after a first online setup, keep the `.venv` folder or prepare a wheelhouse with `prepare_wheelhouse_online.bat`.
