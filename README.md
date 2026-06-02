# Synthwave MIDI Reimaginer GUI v0.2.3

Offline-friendly MIDI analysis, style-based re-arrangement and built-in WAV rendering.

## What this tool does

The app analyzes a source `.mid` / `.midi` file, detects likely track roles such as bass, lead, arp, pad/problem-hook and drums, then creates a new derivative version using a selectable style preset.

It can render a WAV preview internally, so the result does not depend on the Windows MIDI wavetable. MP3 export is optional and only runs when a usable `ffmpeg.exe` is found.

## New in v0.2.3

### Three main generation sliders

The render section now has three musical sliders:

- **Transformation intensity**
  - `0%` = close to source MIDI / cleanup-oriented output
  - `50%` = recognizable source material with a stronger selected-style arrangement
  - `100%` = mostly regenerated song in the selected style, while still using source key and structure as a guide

- **BPM**
  - Sets the target tempo used in the generated MIDI/WAV.
  - The slider is initialized from the selected style's BPM range until the user changes it manually.
  - The selected BPM is written to `_analysis.txt` and is part of reproducible settings.

- **Repeated note amount**
  - `0%` = aggressively reduce long monotone same-note loops by skipping or changing repeated notes.
  - `50%` = balanced motif repetition.
  - `100%` = preserve/allow repetitive patterns, useful for techno, trance, minimal, chiptune, etc.

### More styles

The preset library now includes 57 styles total, including 22+ additional non-electronic or hybrid styles such as Darkwave, Occult Ritual, Meditation, Chillout, Classical, Orchestral Score, Traditional Panflute, Symphonic Metal, Metal, Ska, Punk Rock, Pop, Reggae, Dub, Flower Power, 70s Rock, 20s Jazz, Celtic, Bossa Nova, Latin Electro, Cinematic Trailer and Dream Pop.

### Optional style lead/melody instruments

A new checkbox **Use style lead/melody instruments** lets the selected style override the General MIDI programs for generated lead/hook/pluck/echo tracks. It is OFF by default so changing style mainly changes arrangement behavior first. Turn it ON when you want the lead/melody colors to follow the selected style more strongly, e.g. pan flute, brass, guitars, orchestra or choir-like leads.

### Seed behavior

`New random seed each render` remains ON by default. Turn it off when you want to reproduce a previous seed exactly.

Same seed + same source MIDI + same style + same BPM + same repetition + same settings should reproduce the same MIDI.

## Style Presets

Styles are loaded from:

```text
app/styles/style_presets.json
```

A human-readable CSV overview is included at:

```text
app/styles/electronic_styles.csv
```

You can add a new style by copying an object in `style_presets.json`, changing the `id`, `name`, BPM range, instruments, `drum_feel`, tone ranges and effect values.

## Seed and Random Style behavior

When `New random seed each render` is checked, the GUI chooses a new seed for each render and writes that exact seed to:

- filename, if `{seed}` is used in the prefix
- MIDI metadata
- `_analysis.txt`

When `Random Style from seed` is checked, the style is chosen deterministically from the seed. That means:

```text
same seed + same style preset file = same resolved random style
```

## Output files

A render can create:

- `.mid` new MIDI arrangement
- `.wav` internal audio preview
- `.mp3` optional MP3 export if FFmpeg is available
- `_analysis.txt` with track analysis, seed, source hash, style, BPM, repetition, intensity and rewrite amount

## Windows usage

First run:

```bat
install_windows.bat
```

Later runs:

```bat
run_windows.bat
```

To rebuild the local virtual environment:

```bat
reinstall_windows.bat
```

## Offline notes

After the virtual environment and packages are installed, normal GUI use is offline-capable. For fully offline reinstallations, run `prepare_wheelhouse_online.bat` once on a machine with internet access so the dependency wheels are cached in `wheelhouse/`.
