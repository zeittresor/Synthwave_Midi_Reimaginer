# Synthwave MIDI Reimaginer GUI v0.2.2

Offline-friendly MIDI analysis, style-based re-arrangement and built-in WAV rendering.

## What this tool does

The app analyzes a source `.mid` / `.midi` file, detects likely track roles such as bass, lead, arp, pad/problem-hook and drums, then creates a new derivative electronic version using a selectable style preset.

It can also render a WAV preview internally, so the result does not depend on the Windows MIDI wavetable. MP3 export is optional and only runs when a usable `ffmpeg.exe` is found.

## New in v0.2.2

### Stronger Transformation Intensity

The `Transformation intensity` slider now has a broader musical range:

- `0%` = close to source MIDI / cleanup-oriented output
- `50%` = recognizable source material with a stronger selected-style arrangement
- `100%` = mostly regenerated song in the selected style, while still using source key and structure as a guide

The slider now affects tempo pull, source-note survival, bass pattern generation, arp density, hook composition, lead mutation, pad voicing, support echo and drum variation.

### Stronger Seed Influence

The seed now affects the whole arrangement more clearly:

- bass rhythm and generated bassline choices
- arp sequence templates
- pad chord inversions and progression rewrites
- hook motif generation and phrase rhythm
- lead contour mutations
- drum fills, ghost kicks and hat variation
- echo/support-note selection

Same seed + same source MIDI + same settings should reproduce the same files. Different seeds should now create more audibly different versions.

### Style-aware tooltip

The `Transformation intensity` tooltip is no longer hardcoded to Synthwave. It updates when you change the style preset or activate Random Style.

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
- `_analysis.txt` with track analysis, seed, source hash, style, intensity and rewrite amount

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
