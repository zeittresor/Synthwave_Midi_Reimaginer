# Synthwave MIDI Reimaginer GUI v0.2.7

Offline-friendly PyQt6 GUI for analyzing MIDI files and creating a derivative reimagined version with selectable modular style presets.

Source hint for standalone copies:
`https://github.com/zeittresor/Synthwave_Midi_Reimaginer`


## New in v0.2.7

- Reworked the former **Repeated note amount** control into **Accompaniment relaxation**.
- Moving the slider right now reduces fast repeated accompaniment attacks and creates more breathing room.
- High relaxation values add long harmony-safe pad/string relief layers instead of endless pluck/tick repetitions.
- Dense source-derived arp, glass support and tonal tick tracks are now thinned by the relaxation value.
- The analysis TXT now writes `Accompaniment relaxation` so generated files are easier to diagnose.

## New in v0.2.6

- Expanded style preset library with additional house, grime, hardcore, DnB, rave, rock and experimental styles.
- Added requested styles such as Jump Up, Jersey Club, Footwork, Gabba, French House, Tech House, Goa Trance, Drill, Breakcore, Schranz, Frenchcore, Aggrotech, Japanoise and Death Industrial.
- Presets are still alphabetically sorted and remain editable through `app/styles/style_presets.json`.

## New in v0.2.5

- Added more style presets from user/friend suggestions:
  - Amapiano, Cumbia, Ragga, Electro Swing, UK Bass, UKG, Two Step, Acid Jazz, Rare Groove, Balearic
  - plus Waltz, Cha-Cha-Cha, Salsa, Samba, Rumba, Polka, Bluegrass, New Age, Gregorian Chant, Minimal Wave, EBM, Shoegaze, Industrial Metal, Afro House, Makina, Phonk
- Style presets remain alphabetically sorted.
- Added **Play Source MIDI** for direct comparison with the selected input file.
- Split output playback into **Play MIDI Output** and **Play WAV/MP3 Output**.
- Expanded WAV sample rates: 22050, 32000, 44100, 48000, 96000, 128000 Hz.
- GUI now uses a vertical scroll area, so controls should not be cut off on smaller screens.
- Moved Theme into a dedicated **UI Options** section.
- Themes are now external `.qss` files in `app/themes/`.
- Added themes: Dark, Light, Matrix, Hell, Retro Amber, Ocean.
- Added a language selector in **UI Options**.
- Language files are external JSON files in `app/lang/`.
- Added English and German UI language files.

## Core controls

- **Transformation intensity** controls how strongly the source song is transformed.
- **BPM** controls actual tempo independently from transformation intensity.
- **Accompaniment relaxation** controls how much fast repeated accompaniment is thinned out and replaced with pads/strings/rest space.
- **Seed** controls reproducible variation. Auto Seed is enabled by default.
- **Random Style from seed** chooses a style deterministically from the seed.
- **Use style lead/melody instruments** optionally changes lead/hook/pluck colors to the selected style's GM instrument choices.

## Offline behavior

After `install_windows.bat` has installed the virtual environment once, `run_windows.bat` works offline. For fully offline reinstall on another machine, run `prepare_wheelhouse_online.bat` once on an internet-connected machine and keep the generated `wheelhouse` folder.

## Files

- GUI: `app/midi_reimaginer_gui.py`
- Core engine / CLI: `app/midi_reimaginer_core.py`
- Styles: `app/styles/style_presets.json`
- CSV style overview: `app/styles/electronic_styles.csv`
- Themes: `app/themes/*.qss`
- Languages: `app/lang/*.json`
- Safe generated demo MIDI: `examples/test.mid`

## Example CLI

```bat
.venv\Scripts\python.exe app\midi_reimaginer_core.py examples\test.mid --style amapiano --seed 12345 --bpm 112 --repetition 0.70
```
