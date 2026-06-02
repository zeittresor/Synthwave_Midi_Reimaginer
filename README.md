# Synthwave MIDI Reimaginer GUI v0.2.1


## Hotfix v0.2.1

Fixed a render crash introduced in v0.2.0 where the Support Echo track used `delay_amount` before it was initialized.

Offline-friendly PyQt6 tool that analyzes a MIDI file and creates a cleaned-up electronic derivative version. It can render an internal WAV preview without relying on the Windows MIDI wavetable. MP3 export is optional and uses a real `ffmpeg.exe` when available.

## Start

1. Extract the ZIP.
2. Run `install_windows.bat` once.
3. Run `run_windows.bat`.
4. Choose a `.mid` or `.midi` file.
5. Click **Analyze MIDI**.
6. Choose a **Style Preset**.
7. Click **Create New Version**.

The included example is under `examples/test.mid`.

## New in v0.2.1: Style Presets

The GUI now has a style dropdown. The engine uses the selected style to influence:

- BPM target range
- drum-feel / rhythm family
- bass, lead, arp and pad pitch registers
- note density
- instrument program choices
- brightness, reverb and distortion-like shaping values
- harmony strictness

Included style examples:

- Synthwave
- Retrowave
- Outrun
- Darksynth
- Cyberpunk
- Chillwave
- Vaporwave
- Ambient
- Berlin School
- Electro
- Techno
- Acid Techno
- House
- Deep House
- Trance
- Psytrance
- Drum and Bass
- Liquid Drum and Bass
- Breakbeat
- UK Garage
- Dubstep
- Future Bass
- Trap EDM
- IDM
- Glitch
- Chiptune
- Eurodance
- Hardstyle
- Industrial
- Downtempo
- Trip Hop
- Nu Disco
- Synthpop
- Italo Disco

## Random Style from seed

If **Random Style from seed** is enabled, the selected dropdown style is ignored and the engine chooses one style from the available presets using the generation seed.

That means:

```text
same source MIDI + same seed + same style preset file = same resolved style and same result
```

The resolved style is written into the analysis TXT and into the output filename when `{style}` is used.

## Seeds

- **New random seed each render**: creates a new seed for each render.
- **Manual seed**: repeats the same version exactly when settings and input are unchanged.

The seed is written to:

- output filename if `{seed}` is used
- MIDI metadata
- `_analysis.txt`

## Filename placeholders

The filename prefix field supports:

```text
{source}       input MIDI filename without extension
{style}        resolved style id
{style_name}   resolved style name as a safe token
{seed}         actual generation seed
{source_hash}  SHA-256 hash prefix of the source MIDI
```

Default:

```text
{source}_{style}_seed{seed}
```

## Modular style files

Style presets live here:

```text
app/styles/style_presets.json
```

A human-readable table is included here:

```text
app/styles/electronic_styles.csv
```

To add a style, copy an existing JSON object, give it a unique `id`, change the musical values, and restart the GUI.

Important fields:

```text
id
name
instruments
meter
info
bpm_min
bpm_max
swing
drum_feel
bass_center
lead_center
arp_density
pad_density
brightness
distortion
reverb
delay
harmony_strictness
programs
```

## CLI examples

Manual style:

```bat
.venv\Scripts\python.exe app\midi_reimaginer_core.py examples\test.mid --out-dir output --style darksynth --seed 123456
```

Random style from seed:

```bat
.venv\Scripts\python.exe app\midi_reimaginer_core.py examples\test.mid --out-dir output --random-style --seed 123456
```

## Offline behavior

After `install_windows.bat` has installed the local `.venv` once, `run_windows.bat` works offline.

For preparing dependencies for another offline machine, run:

```bat
prepare_wheelhouse_online.bat
```

on an internet-connected system and keep the generated `wheelhouse` folder with the project.

## MP3 export

MP3 export needs a real FFmpeg binary. The tool validates `ffmpeg -version` and ignores fake Python package shims named `ffmpeg.exe`. If MP3 conversion fails, MIDI and WAV are still created.

## Current limitations

This is still a heuristic MIDI re-arranger, not a full composition AI or DAW. The results depend heavily on the source MIDI. Very disharmonic, key-changing or sparse source files can still produce odd moments, but Harmony Lock and style-specific harmony strictness should reduce the worst clashes.
