# Synthwave MIDI Reimaginer GUI

Reimaginer any midi song you like. With Parameter, Midi, WAV, MP3 output for any random or reproduceable seed you set. 

<img width="1183" height="811" alt="Synthwave_Midi_Reimaginer" src="https://github.com/user-attachments/assets/0703af27-d0e1-4706-9d0f-7352fecc7eaa" />

## Start on Windows

1. Run `install_windows.bat`
2. After setup, run `run_windows.bat`
3. Choose a `.mid` or `.midi` file
4. Click **Analyze MIDI**
5. Click **Create New Version**

The installer creates a local `.venv` folder. After the first successful setup, the GUI can run offline via `run_windows.bat`.

## Files in this package

- `app/midi_reimaginer_gui.py` - PyQt6 GUI
- `app/midi_reimaginer_core.py` - MIDI parser, analyzer, transformer, WAV renderer, optional MP3 converter
- `install_windows.bat` - creates `.venv` and installs requirements
- `run_windows.bat` - starts the GUI
- `reinstall_windows.bat` - removes `.venv` and reinstalls
- `prepare_wheelhouse_online.bat` - downloads dependency wheels for future offline reinstall
- `run_cli_example.bat` - command-line example using `examples/test.mid`
- `legacy/make_fixed_synthwave_v2.py` - the previous manual script for reference

## Offline reinstall / wheelhouse mode

For a fully offline reinstall on the same or a very similar Windows/Python setup:

1. On an internet-connected machine, run `prepare_wheelhouse_online.bat`.
2. Keep the generated `wheelhouse` folder together with this package.
3. Later, `install_windows.bat` will automatically prefer `wheelhouse` and install without internet.

Note: PyQt6 wheels are Python-version and platform specific. A wheelhouse prepared on Python 3.12 Windows x64 is intended for the same kind of setup.

## MP3 export and the ffmpeg fix

The earlier script failed on this console output:

```text
Unrecognized option 'hide_banner'.
Error splitting the argument list: Option not found
```

That usually means that the executable found as `ffmpeg.EXE` is not a real FFmpeg binary or is a limited shim. This GUI fixes that in two ways:

1. It validates candidates with `ffmpeg -version` and requires the output to contain `ffmpeg version`.
2. It no longer depends on `-hide_banner`.

If no real ffmpeg is found, MP3 is skipped safely. The WAV file is still created.

Supported ffmpeg locations:

- `SYNTHWAVE_FFMPEG` environment variable
- `tools/ffmpeg/bin/ffmpeg.exe`
- `tools/ffmpeg/ffmpeg.exe`
- `portable_ffmpeg/ffmpeg.exe`
- a real `ffmpeg.exe` on PATH

## Command-line usage

```bat
.venv\Scripts\python.exe app\midi_reimaginer_core.py input.mid --out-dir output --prefix my_song_v2
```

Options:

```text
--no-audio       Only create MIDI and analysis text
--no-mp3         Skip MP3 conversion
--sample-rate    44100 or 48000 recommended
--intensity      Transformation strength from 0.0 to 1.0
```

## Current limits

This is a heuristic MIDI re-arranger, not a full AI music model. It should work best with structured multi-track MIDI files. Very sparse one-track files or unusual SMPTE-time MIDI files may need manual cleanup.

## Source

github.com/zeittresor/Synthwave_Midi_Reimaginer
