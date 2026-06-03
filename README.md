# Synthwave MIDI Reimaginer GUI v0.2.4

Offline-friendly PyQt6 tool for analyzing a source MIDI file and generating a new reimagined MIDI/WAV/optional MP3 version with selectable modular style presets.

Source/project note for standalone copies:
https://github.com/zeittresor/Synthwave_Midi_Reimaginer

## New in v0.2.4

- Added more style presets, including:
  - Bebop
  - Blues
  - Baroque
  - Church Music
  - Disco
  - Epic Fantasy
  - Flamenco
  - Funk
  - Gospel
  - Gypsy Swing
  - Hip Hop
  - Holy Ambient
  - Klezmer
  - Lo-Fi Hip Hop
  - Medieval
  - Moombahton
  - Modern Pop
  - No Drums / Percussion
  - R&B
  - Reggaeton
  - Simple Piano
  - Soul
  - Surf Rock
  - Tango
  - Western
- Style presets are now alphabetically sorted in the JSON file and in the GUI drop-down.
- Added drum engine support for:
  - `no_drums` / `no_percussion` / `silent`
  - `moombahton` / `reggaeton`
  - `hip_hop`
  - `funk`
- Replaced the bundled example MIDI with a generated safe demo melody instead of the earlier uploaded test material.
- Added source comments near the top of Python and batch files.

## Basic usage

1. Run `install_windows.bat` once.
2. Run `run_windows.bat`.
3. Select a `.mid` or `.midi` source file.
4. Click **Analyze MIDI**.
5. Choose a style, BPM, transformation intensity and repeated-note amount.
6. Click **Create New Version**.

Generated files are written into the selected output folder.

## Important controls

- **Style**: Selects the target musical direction.
- **Random Style from seed**: Picks a style deterministically from the seed.
- **Transformation intensity**: Controls how strongly the source is rewritten.
- **BPM**: Controls the actual output tempo.
- **Repeated note amount**: Controls how much repetitive note hammering is preserved or reduced.
- **New random seed each render**: Default ON. Every render gets a new seed. Disable it to reproduce a previous result.
- **Use style lead/melody instruments**: Default OFF. Enable it to force style-specific General MIDI lead/hook/pluck colors.

## Style files

The style system is modular:

- `app/styles/style_presets.json` is used by the engine.
- `app/styles/electronic_styles.csv` is a readable overview table.

New styles can be added by appending objects to the JSON file. The engine fills missing fields with safe defaults, but the best results come from complete presets.

## Offline notes

After the first setup has downloaded wheels into the local environment or wheelhouse, the program can run offline. WAV rendering is internal and does not need the Windows wavetable. MP3 export is optional and needs a real `ffmpeg.exe`.
