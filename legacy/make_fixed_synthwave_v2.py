#!/usr/bin/env python3
"""
Create a cleaned-up/re-imagined MIDI version from test.mid and render an audio preview.

Output files by default:
  test_reimagined_synthwave_v2_fixed.mid
  test_reimagined_synthwave_v2_fixed.wav
  test_reimagined_synthwave_v2_fixed.mp3  (if ffmpeg is available)

This script intentionally does NOT rely on the Windows wavetable synth.  The WAV is rendered
with a small built-in Python synthesizer so timing and instrument choices are deterministic.
Dependencies for WAV rendering: numpy + scipy.  MP3 conversion uses ffmpeg if installed.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict, Counter
import argparse
import math
import random
import subprocess
import shutil
import wave

# -----------------------------
# Minimal MIDI reader / writer
# -----------------------------
@dataclass
class Event:
    abs_tick: int
    delta: int
    type: str
    status: int | None = None
    channel: int | None = None
    data: bytes = b""
    meta_type: int | None = None
    raw: bytes = b""
    desc: str = ""
    order: int = 10

@dataclass
class Track:
    events: list[Event] = field(default_factory=list)
    name: str = ""


def read_var(data: bytes, i: int) -> tuple[int, int]:
    value = 0
    while True:
        b = data[i]
        i += 1
        value = (value << 7) | (b & 0x7F)
        if not (b & 0x80):
            break
    return value, i


def write_var(v: int) -> bytes:
    v = max(0, int(v))
    if v == 0:
        return b"\x00"
    parts = [v & 0x7F]
    v >>= 7
    while v:
        parts.append((v & 0x7F) | 0x80)
        v >>= 7
    return bytes(reversed(parts))


def parse_midi(path: Path):
    data = path.read_bytes()
    i = 0
    if data[i:i+4] != b"MThd":
        raise ValueError("Not a standard MIDI file")
    i += 4
    hdr_len = int.from_bytes(data[i:i+4], "big"); i += 4
    fmt = int.from_bytes(data[i:i+2], "big")
    ntr = int.from_bytes(data[i+2:i+4], "big")
    div = int.from_bytes(data[i+4:i+6], "big")
    i += hdr_len
    tracks: list[Track] = []
    for ti in range(ntr):
        if data[i:i+4] != b"MTrk":
            raise ValueError(f"Missing MTrk at track {ti}")
        i += 4
        length = int.from_bytes(data[i:i+4], "big"); i += 4
        end = i + length
        evs: list[Event] = []
        abs_tick = 0
        running: int | None = None
        name = ""
        while i < end:
            delta, i = read_var(data, i)
            abs_tick += delta
            b = data[i]; i += 1
            if b == 0xFF:
                meta_type = data[i]; i += 1
                l, i = read_var(data, i)
                dat = data[i:i+l]; i += l
                desc = ""
                if meta_type == 0x03:
                    try:
                        name = dat.decode("latin1")
                    except Exception:
                        name = repr(dat)
                    desc = name
                evs.append(Event(abs_tick, delta, "meta", None, None, dat, meta_type, desc=desc))
            elif b in (0xF0, 0xF7):
                l, i = read_var(data, i)
                dat = data[i:i+l]; i += l
                evs.append(Event(abs_tick, delta, "sysex", b, None, dat))
                running = None
            else:
                if b & 0x80:
                    status = b
                    running = status
                    hi = status & 0xF0
                    ch = status & 0x0F
                    l = 1 if hi in (0xC0, 0xD0) else 2
                    dat = data[i:i+l]; i += l
                else:
                    if running is None:
                        raise ValueError("Running status without prior status")
                    status = running
                    hi = status & 0xF0
                    ch = status & 0x0F
                    l = 1 if hi in (0xC0, 0xD0) else 2
                    dat = bytes([b]) + data[i:i+l-1]; i += l-1
                typ = {
                    0x80:"note_off", 0x90:"note_on", 0xA0:"poly_aftertouch", 0xB0:"control_change",
                    0xC0:"program_change", 0xD0:"channel_aftertouch", 0xE0:"pitch_bend",
                }.get(status & 0xF0, "midi")
                evs.append(Event(abs_tick, delta, typ, status, ch, dat))
        tracks.append(Track(evs, name))
    return fmt, ntr, div, tracks


def event_raw(ev: Event) -> bytes:
    if ev.type == "meta":
        return bytes([0xFF, ev.meta_type or 0]) + write_var(len(ev.data)) + ev.data
    if ev.type == "sysex":
        return bytes([ev.status or 0xF0]) + write_var(len(ev.data)) + ev.data
    if ev.status is None:
        return ev.raw
    return bytes([ev.status]) + ev.data


def write_midi(path: Path, fmt: int, division: int, tracks_events: list[list[Event]]):
    out = bytearray()
    out += b"MThd" + (6).to_bytes(4,"big") + fmt.to_bytes(2,"big") + len(tracks_events).to_bytes(2,"big") + division.to_bytes(2,"big")
    for evs in tracks_events:
        evs = sorted(enumerate(evs), key=lambda x: (x[1].abs_tick, x[1].order, x[0]))
        body = bytearray()
        prev = 0
        has_end = False
        for _, ev in evs:
            dt = max(0, int(round(ev.abs_tick)) - prev)
            prev += dt
            body += write_var(dt) + event_raw(ev)
            if ev.type == "meta" and ev.meta_type == 0x2F:
                has_end = True
        if not has_end:
            body += write_var(0) + b"\xFF\x2F\x00"
        out += b"MTrk" + len(body).to_bytes(4,"big") + body
    path.write_bytes(out)


def make_meta(abs_tick: int, meta_type: int, data: bytes, order: int = 0) -> Event:
    return Event(int(abs_tick), 0, "meta", None, None, bytes(data), meta_type, order=order)


def make_midi(abs_tick: int, status: int, data: list[int] | bytes, order: int = 10) -> Event:
    hi = status & 0xF0
    typ = {0x80:"note_off",0x90:"note_on",0xA0:"poly_aftertouch",0xB0:"control_change",0xC0:"program_change",0xD0:"channel_aftertouch",0xE0:"pitch_bend"}.get(hi,"midi")
    return Event(int(abs_tick), 0, typ, status, status & 0x0F, bytes(data), order=order)

# -----------------------------
# Musical transformation
# -----------------------------
def clip(v, lo, hi):
    return max(lo, min(hi, int(round(v))))


def quantize_tick(t: int, grid: int) -> int:
    return int(round(t / grid) * grid)


def extract_notes(track: Track, song_end: int):
    stacks = defaultdict(list)
    notes = []
    order = 0
    for e in track.events:
        if e.channel is None or not e.data or e.status is None:
            order += 1
            continue
        hi = e.status & 0xF0
        if hi == 0x90 and len(e.data) >= 2 and e.data[1] > 0:
            stacks[(e.channel, e.data[0])].append((e.abs_tick, e.data[1], order))
        elif (hi == 0x80 and len(e.data) >= 2) or (hi == 0x90 and len(e.data) >= 2 and e.data[1] == 0):
            key = (e.channel, e.data[0])
            if stacks[key]:
                st, vel, o = stacks[key].pop(0)
                if e.abs_tick > st:
                    notes.append({"start": st, "end": e.abs_tick, "pitch": e.data[0], "vel": vel, "ch": e.channel, "order": o})
        order += 1
    for (ch, pitch), qs in stacks.items():
        for st, vel, o in qs:
            notes.append({"start": st, "end": min(st+384, song_end), "pitch": pitch, "vel": vel, "ch": ch, "order": o})
    notes.sort(key=lambda n: (n["start"], n["pitch"], n["order"]))
    return notes


def add_note(evs: list[Event], ch: int, pitch: int, start: int, duration: int, vel: int = 90, order_on: int = 30):
    pitch = clip(pitch, 0, 127)
    start = max(0, int(round(start)))
    dur = max(12, int(round(duration)))
    end = start + dur
    evs.append(make_midi(start, 0x90 | ch, [pitch, clip(vel, 1, 127)], order=order_on))
    evs.append(make_midi(end, 0x80 | ch, [pitch, 64], order=20))


def setup_track(name: str, ch: int | None = None, program: int | None = None, volume=100, pan=64, reverb=24, chorus=18):
    evs = [make_meta(0, 0x03, name.encode("latin1", errors="replace"), order=0)]
    if ch is not None:
        if program is not None:
            evs.append(make_midi(0, 0xC0 | ch, [program], order=1))
        evs.append(make_midi(0, 0xB0 | ch, [7, volume], order=2))
        evs.append(make_midi(0, 0xB0 | ch, [10, pan], order=3))
        evs.append(make_midi(0, 0xB0 | ch, [91, reverb], order=4))
        evs.append(make_midi(0, 0xB0 | ch, [93, chorus], order=5))
    return evs


def build_reimagined_midi(src: Path, out_mid: Path):
    random.seed(20260527)
    fmt, ntr, div, tracks = parse_midi(src)
    bar = div * 4
    song_end = max(e.abs_tick for e in tracks[0].events)  # original end marker is reliable here
    all_notes = [extract_notes(t, song_end) for t in tracks]

    # More conservative than the first draft: 120 BPM, straight 16th-grid for instruments.
    tempo = int(round(60_000_000 / 120))
    new_tracks: list[list[Event]] = []
    t0 = [
        make_meta(0, 0x03, b"Synthwave v2 - fixed timing", order=0),
        make_meta(0, 0x51, tempo.to_bytes(3,"big"), order=1),
        make_meta(0, 0x58, bytes([4,2,24,8]), order=2),
    ]
    for b, label in [(0,b"INTRO"),(8,b"GROOVE"),(24,b"WARM HOOK"),(48,b"CHORUS"),(64,b"ALT CHORUS"),(80,b"OUTRO")]:
        if b*bar < song_end:
            t0.append(make_meta(b*bar, 0x06, label, order=4))
    t0.append(make_meta(song_end, 0x2F, b"", order=99))
    new_tracks.append(t0)

    # Bass: quantized, locked, no random timing. Keep recognisable motif but shorten notes slightly.
    bass = setup_track("LOCKED SYNTH BASS", ch=1, program=38, volume=116, pan=48, reverb=12, chorus=18)
    for n in all_notes[1]:
        st = quantize_tick(n["start"], div//4)  # 16th grid
        dur = max(div//8, quantize_tick(n["end"] - n["start"], div//8))
        dur = int(dur * 0.88)
        add_note(bass, 1, n["pitch"], st, dur, n["vel"] * 0.95)
        if n["start"] >= 48*bar and (st // (div//2)) % 8 == 0 and n["pitch"] >= 36:
            add_note(bass, 1, n["pitch"] - 12, st, min(dur, div//2), n["vel"] * 0.38)
    bass.append(make_meta(song_end,0x2F,b"",order=99)); new_tracks.append(bass)

    # Former high muted guitar: move down and make it a clean plucked counter-rhythm.
    pluck = setup_track("LOW FM PLUCK", ch=2, program=5, volume=82, pan=82, reverb=36, chorus=25)
    for i, n in enumerate(all_notes[2]):
        st = quantize_tick(n["start"], div//4)
        dur = max(div//8, int((n["end"] - n["start"]) * 0.62))
        pitch = n["pitch"] - 24
        if n["start"] >= 64*bar and i % 4 == 0:
            pitch += 7
        add_note(pluck, 2, pitch, st, dur, n["vel"] * 0.62)
    pluck.append(make_meta(song_end,0x2F,b"",order=99)); new_tracks.append(pluck)

    # Marimba -> glass/vibe arp, reduced density and consistent timing.
    vibe = setup_track("GLASS VIBE ARP CLEAN", ch=3, program=11, volume=86, pan=36, reverb=50, chorus=30)
    for i, n in enumerate(all_notes[3]):
        if i % 9 == 8 and n["start"] > 24*bar:
            continue
        st = quantize_tick(n["start"], div//4)
        dur = max(36, int((n["end"] - n["start"]) * 0.55))
        pitch = n["pitch"]
        if pitch > 82:
            pitch -= 12
        add_note(vibe, 3, pitch, st, dur, n["vel"] * 0.58)
    vibe.append(make_meta(song_end,0x2F,b"",order=99)); new_tracks.append(vibe)

    # Woodblock: turn into short tonal ticks; keep rhythm but less manic and less prominent.
    blocks = setup_track("SOFT PERC TICKS", ch=4, program=115, volume=62, pan=96, reverb=20, chorus=6)
    for i, n in enumerate(all_notes[4]):
        if i % 3 == 2:  # thin out dense block chatter
            continue
        st = quantize_tick(n["start"], div//8)  # 32nd grid, but clean
        dur = max(24, min(div//5, n["end"] - n["start"]))
        pitch = 76 + ((i // 4) % 5)  # no 100+ squeak range
        add_note(blocks, 4, pitch, st, dur, 48 + (i % 4) * 6)
    blocks.append(make_meta(song_end,0x2F,b"",order=99)); new_tracks.append(blocks)

    # Chords from bass roots. Warm pad glues the track together.
    scale = [5,7,8,10,0,1,3]  # F natural minor-ish palette: F G Ab Bb C Db Eb
    def nearest_pitch(pc: int, center: int):
        return min([pc + 12*o for o in range(2,8)], key=lambda p: abs(p-center))
    roots = []
    for st in range(0, song_end, bar*2):
        c = Counter()
        for n in all_notes[1]:
            if st <= n["start"] < st + bar*2:
                c[n["pitch"] % 12] += max(1, n["end"] - n["start"])
        root = c.most_common(1)[0][0] if c else (roots[-1][1] if roots else 5)
        if root not in scale:
            root = min(scale, key=lambda pc: min((pc-root)%12, (root-pc)%12))
        roots.append((st, root))
    pad = setup_track("WARM ANALOG PAD", ch=5, program=89, volume=72, pan=62, reverb=72, chorus=55)
    for idx, (st, root) in enumerate(roots):
        if st < 4*bar:
            continue
        deg = scale.index(root)
        pcs = [scale[deg], scale[(deg+2)%7], scale[(deg+4)%7]]
        if idx % 3 == 1:
            pcs.append(scale[(deg+6)%7])
        chord_start = st
        chord_dur = min(bar*2 - div//4, song_end - st)
        for j, pc in enumerate(pcs):
            p = nearest_pitch(pc, 58 + j*4)
            if j == 0 and p > 55:
                p -= 12
            add_note(pad, 5, p, chord_start + j*4, chord_dur - j*4, 45 + j*6)
    pad.append(make_meta(song_end,0x2F,b"",order=99)); new_tracks.append(pad)

    # The originally awful/squeaky STRINGS idea becomes this hook: same contour, down 3 octaves,
    # quantized as a controlled call/response motif in chorus sections.
    hook = setup_track("ICON HOOK - DE-SQUEAKED", ch=6, program=80, volume=88, pan=28, reverb=42, chorus=38)
    source_hook_notes = all_notes[5]
    if source_hook_notes:
        motif = [clip(n["pitch"] - 36, 60, 76) for n in source_hook_notes[:4]]
    else:
        motif = [72, 70, 68, 65]
    sections = [24, 32, 48, 56, 64, 72]
    for sec in sections:
        base = sec * bar
        if base >= song_end:
            continue
        for rep in range(2):
            phrase = base + rep * bar * 2
            if phrase >= song_end:
                continue
            # rhythm: long-short-short-long, always grid-aligned
            starts = [phrase, phrase + div, phrase + div + div//2, phrase + 2*div + div//2]
            durs = [div*3//4, div//3, div//3, div]
            for k, p in enumerate(motif):
                add_note(hook, 6, p + (12 if sec >= 64 and k == 0 else 0), starts[k], durs[k], 84 - k*5)
            # gentle answer one octave lower
            answer = phrase + 3*div
            if answer < song_end:
                for k, p in enumerate(reversed(motif[1:])):
                    add_note(hook, 6, p - 12, answer + k*(div//2), div//3, 55 - k*4)
    hook.append(make_meta(song_end,0x2F,b"",order=99)); new_tracks.append(hook)

    # Bandoneon melody: keep useful contour, clamp excessive high notes.
    lead = setup_track("ROUNDED LEAD CONTOUR", ch=7, program=81, volume=78, pan=104, reverb=44, chorus=34)
    last_st = -9999
    for i, n in enumerate(all_notes[6]):
        st = quantize_tick(n["start"], div//4)
        if st == last_st and i % 2:
            continue
        last_st = st
        dur = max(div//8, int((n["end"] - n["start"]) * 0.72))
        pitch = n["pitch"]
        while pitch > 84:
            pitch -= 12
        if pitch < 55 and n["start"] > 48*bar:
            pitch += 12
        add_note(lead, 7, pitch, st, dur, n["vel"] * 0.68)
    lead.append(make_meta(song_end,0x2F,b"",order=99)); new_tracks.append(lead)

    # Existing saw line: less high, less busy, as a supporting echo synth.
    echo = setup_track("SUPPORT SAW ECHO", ch=8, program=88, volume=66, pan=72, reverb=52, chorus=44)
    for i, n in enumerate(all_notes[7]):
        if i % 11 == 10:
            continue
        st = quantize_tick(n["start"], div//4)
        dur = max(div//6, int((n["end"] - n["start"]) * 0.82))
        pitch = n["pitch"]
        if pitch < 55:
            pitch += 12
        if pitch > 82:
            pitch -= 12
        add_note(echo, 8, pitch, st, dur, n["vel"] * 0.54)
        if i % 8 == 3 and st + div//2 < song_end:
            add_note(echo, 8, pitch, st + div//2, dur//2, n["vel"] * 0.24)
    echo.append(make_meta(song_end,0x2F,b"",order=99)); new_tracks.append(echo)

    # Drums: grid-locked 4/4 synthwave kit. No per-note humanize here, so it should not feel out of time.
    drums = setup_track("GRIDLOCK DRUMS", ch=9, program=None, volume=122, pan=64, reverb=18, chorus=4)
    start_drum = 2*bar
    for bs in range(start_drum, song_end, bar):
        bar_i = bs // bar
        # kick
        for beat in range(4):
            add_note(drums, 9, 36, bs + beat*div, 42, 108 if beat == 0 else 98)
        if bar_i % 4 in (1,3):
            add_note(drums, 9, 36, bs + 3*div + div//2, 36, 74)
        # snare/clap
        for beat in (1,3):
            add_note(drums, 9, 38, bs + beat*div, 50, 100)
            add_note(drums, 9, 39, bs + beat*div + 10, 48, 58)
        # hats: slight deterministic swing only on hats (timing of other instruments remains straight)
        for e8 in range(8):
            swing = div//14 if e8 % 2 == 1 else 0
            add_note(drums, 9, 42, bs + e8*(div//2) + swing, 28, 58 + (18 if e8 % 2 == 0 else 0))
        add_note(drums, 9, 46, bs + 2*div + div//2 + div//14, 55, 60)
        if bar_i % 16 == 0:
            add_note(drums, 9, 49, bs, div, 72)
        if bar_i % 8 == 7:
            for k, note in enumerate([47,45,43,41]):
                add_note(drums, 9, note, bs + 3*div + k*(div//4), 52, 78-k*5)
    drums.append(make_meta(song_end,0x2F,b"",order=99)); new_tracks.append(drums)

    reset = [make_meta(0,0x03,b"GS/RESET",order=0)]
    if len(tracks) > 9:
        for e in tracks[9].events:
            if e.type == "sysex":
                reset.append(Event(0,0,"sysex",e.status,None,e.data,order=1))
    reset.append(make_meta(song_end,0x2F,b"",order=99)); new_tracks.append(reset)

    write_midi(out_mid, 1, div, new_tracks)
    return out_mid, div, tempo, song_end

# -----------------------------
# Built-in WAV renderer
# -----------------------------
def midi_to_freq(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def parse_tempo(mid: Path):
    fmt, ntr, div, tracks = parse_midi(mid)
    tempo = 500000
    for e in tracks[0].events:
        if e.type == "meta" and e.meta_type == 0x51 and len(e.data) == 3:
            tempo = int.from_bytes(e.data, "big")
            break
    return fmt, ntr, div, tracks, tempo


def collect_notes_for_render(mid: Path):
    fmt, ntr, div, tracks, tempo = parse_tempo(mid)
    end_tick = max(e.abs_tick for t in tracks for e in t.events)
    sp_tick = (tempo / 1_000_000.0) / div
    notes = []
    programs = defaultdict(lambda: 0)
    volumes = defaultdict(lambda: 100)
    pans = defaultdict(lambda: 64)
    for ti, t in enumerate(tracks):
        stacks = defaultdict(list)
        for e in t.events:
            if e.status is None or e.channel is None:
                continue
            hi = e.status & 0xF0
            ch = e.channel
            if hi == 0xC0 and e.data:
                programs[ch] = e.data[0]
            elif hi == 0xB0 and len(e.data) >= 2:
                if e.data[0] == 7:
                    volumes[ch] = e.data[1]
                elif e.data[0] == 10:
                    pans[ch] = e.data[1]
            elif hi == 0x90 and len(e.data) >= 2 and e.data[1] > 0:
                stacks[(ch, e.data[0])].append((e.abs_tick, e.data[1], programs[ch], volumes[ch], pans[ch]))
            elif (hi == 0x80 and len(e.data) >= 2) or (hi == 0x90 and len(e.data) >= 2 and e.data[1] == 0):
                key = (ch, e.data[0])
                if stacks[key]:
                    st, vel, prog, vol, pan = stacks[key].pop(0)
                    if e.abs_tick > st:
                        notes.append({
                            "start": st * sp_tick,
                            "dur": max(0.03, (e.abs_tick - st) * sp_tick),
                            "pitch": e.data[0], "vel": vel, "ch": ch, "program": prog, "vol": vol, "pan": pan,
                            "track": ti,
                        })
    duration = end_tick * sp_tick + 2.0
    return notes, duration


def envelope(n: int, sr: int, attack=0.008, decay=0.05, sustain=0.7, release=0.04):
    if n <= 0:
        return []
    import numpy as np
    a = min(n, int(attack * sr))
    d = min(max(0, n-a), int(decay * sr))
    r = min(max(0, n-a-d), int(release * sr))
    s = max(0, n-a-d-r)
    parts = []
    if a:
        parts.append(np.linspace(0, 1, a, endpoint=False))
    if d:
        parts.append(np.linspace(1, sustain, d, endpoint=False))
    if s:
        parts.append(np.full(s, sustain))
    if r:
        parts.append(np.linspace(sustain, 0, r, endpoint=True))
    if not parts:
        return np.ones(n)
    env = np.concatenate(parts)
    if len(env) < n:
        env = np.pad(env, (0, n-len(env)), constant_values=0)
    return env[:n]


def softclip(x):
    import numpy as np
    return np.tanh(x)


def synth_note(note, sr: int):
    import numpy as np
    ch = note["ch"]
    pitch = note["pitch"]
    dur = note["dur"]
    vel = note["vel"] / 127.0
    vol = note["vol"] / 127.0
    amp = vel * vol
    n = max(1, int((dur + 0.08) * sr))
    t = np.arange(n, dtype=np.float32) / sr
    f = midi_to_freq(pitch)

    if ch == 9:
        # GM-ish percussion: deterministic synth kit
        if pitch == 36:  # kick
            n2 = max(1, int(0.42 * sr)); t2 = np.arange(n2)/sr
            freq = 95*np.exp(-t2*22) + 38
            phase = 2*np.pi*np.cumsum(freq)/sr
            wave = np.sin(phase) * np.exp(-t2*9.5)
            wave += 0.25*np.random.default_rng(1000+pitch+n2).normal(0,1,n2)*np.exp(-t2*45)
            return wave.astype(np.float32) * amp * 1.15
        if pitch in (38,39):  # snare / clap
            n2 = max(1, int(0.34 * sr)); t2 = np.arange(n2)/sr
            rng = np.random.default_rng(2000+pitch+n2)
            noise = rng.normal(0,1,n2)
            tone = np.sin(2*np.pi*185*t2) * np.exp(-t2*14)
            wave = (0.65*noise*np.exp(-t2*17) + 0.35*tone)
            if pitch == 39:
                wave *= (1 + 0.35*np.sin(2*np.pi*34*t2))
            return wave.astype(np.float32) * amp * 0.72
        if pitch in (42,46,49):  # hats/crash
            n2 = max(1, int((0.08 if pitch==42 else 0.38 if pitch==46 else 1.1)*sr)); t2 = np.arange(n2)/sr
            rng = np.random.default_rng(3000+pitch+n2)
            noise = rng.normal(0,1,n2)
            # crude high-pass by subtracting a smoothed version
            smooth = np.convolve(noise, np.ones(16)/16, mode='same')
            wave = (noise - smooth) * np.exp(-t2*(38 if pitch==42 else 7 if pitch==46 else 2.2))
            return wave.astype(np.float32) * amp * (0.23 if pitch==42 else 0.30)
        # toms
        n2 = max(1, int(0.28*sr)); t2 = np.arange(n2)/sr
        base = {47:190,45:155,43:125,41:95}.get(pitch, 160)
        wave = np.sin(2*np.pi*(base*np.exp(-t2*3.5))*t2) * np.exp(-t2*8)
        return wave.astype(np.float32) * amp * 0.58

    # Melodic channel synthesis
    phase = 2*np.pi*f*t
    if ch == 1:  # locked bass: rounded square + sub
        wave = 0.58*np.tanh(2.2*np.sin(phase)) + 0.32*np.sin(phase*0.5)
        env = envelope(n, sr, attack=0.004, decay=0.04, sustain=0.62, release=0.035)
        wave *= env * 0.55
    elif ch == 2:  # low FM pluck
        wave = np.sin(phase + 1.8*np.sin(2*phase)*np.exp(-t*7.0))
        wave += 0.22*np.sin(2*phase)
        env = envelope(n, sr, attack=0.003, decay=0.18, sustain=0.12, release=0.055)
        wave *= env * 0.34
    elif ch == 3:  # glass/vibe
        wave = np.sin(phase) + 0.35*np.sin(2.01*phase) + 0.18*np.sin(3.02*phase)
        env = envelope(n, sr, attack=0.006, decay=0.22, sustain=0.22, release=0.09)
        wave *= env * 0.24
    elif ch == 4:  # soft ticks
        wave = np.sin(phase) + 0.22*np.sin(3*phase)
        env = envelope(n, sr, attack=0.001, decay=0.035, sustain=0.08, release=0.025)
        wave *= env * 0.13
    elif ch == 5:  # warm pad
        det = 0.006
        wave = 0.42*np.sin(phase) + 0.22*np.sin(2*np.pi*f*(1+det)*t) + 0.22*np.sin(2*np.pi*f*(1-det)*t)
        wave += 0.08*np.sin(2*phase)
        env = envelope(n, sr, attack=0.25, decay=0.22, sustain=0.82, release=0.35)
        wave *= env * 0.28
    elif ch == 6:  # de-squeaked hook
        vibr = 0.003*np.sin(2*np.pi*5.2*t)
        wave = 0.48*np.tanh(1.7*np.sin(phase*(1+vibr))) + 0.24*np.sin(phase) + 0.12*np.sin(2*phase)
        env = envelope(n, sr, attack=0.012, decay=0.08, sustain=0.72, release=0.075)
        wave *= env * 0.36
    elif ch == 7:  # rounded lead
        wave = 0.35*np.tanh(2.0*np.sin(phase)) + 0.28*np.sin(phase) + 0.10*np.sin(2*phase)
        env = envelope(n, sr, attack=0.01, decay=0.08, sustain=0.56, release=0.07)
        wave *= env * 0.30
    elif ch == 8:  # support saw-ish echo, softened
        frac = (f*t) % 1.0
        saw = 2*frac - 1
        wave = 0.22*saw + 0.30*np.sin(phase)
        env = envelope(n, sr, attack=0.01, decay=0.10, sustain=0.48, release=0.085)
        wave *= env * 0.21
    else:
        wave = np.sin(phase) * envelope(n, sr)
        wave *= 0.2
    return (wave.astype(np.float32) * amp)


def render_wav(mid: Path, wav_path: Path, sr: int = 44100):
    import numpy as np
    from scipy.io import wavfile
    random.seed(20260527)
    np.random.seed(20260527)
    notes, duration = collect_notes_for_render(mid)
    total = int(duration * sr)
    mix = np.zeros((total, 2), dtype=np.float32)
    for note in notes:
        audio = synth_note(note, sr)
        start = int(note["start"] * sr)
        end = min(total, start + len(audio))
        if end <= start:
            continue
        audio = audio[:end-start]
        pan = note["pan"] / 127.0
        left = math.cos(pan * math.pi/2)
        right = math.sin(pan * math.pi/2)
        mix[start:end,0] += audio * left
        mix[start:end,1] += audio * right
    # Simple delay/reverb send for more pleasant preview
    delay_s = int(0.28 * sr)
    if delay_s < total:
        mix[delay_s:] += mix[:-delay_s] * 0.16
    delay_s2 = int(0.43 * sr)
    if delay_s2 < total:
        mix[delay_s2:] += mix[:-delay_s2] * 0.08
    # Fade out
    fade_len = min(total, int(2.0*sr))
    if fade_len:
        fade = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
        mix[-fade_len:] *= fade[:,None]
    # Normalize with headroom and soft clip
    peak = float(np.max(np.abs(mix))) if total else 1.0
    if peak > 0:
        mix = mix / max(peak, 1.0) * 0.92
    mix = softclip(mix * 1.15) * 0.88
    out = np.int16(np.clip(mix, -1, 1) * 32767)
    wavfile.write(wav_path, sr, out)
    return wav_path


def convert_mp3(wav_path: Path, mp3_path: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return None
    cmd = [ffmpeg, "-y", "-hide_banner", "-loglevel", "error", "-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3_path)]
    subprocess.run(cmd, check=True)
    return mp3_path


def main():
    ap = argparse.ArgumentParser(description="Create a fixed-timing synthwave MIDI variation and render WAV/MP3 preview.")
    ap.add_argument("source", nargs="?", default="test.mid", help="Input MIDI file")
    ap.add_argument("--prefix", default="test_reimagined_synthwave_v2_fixed", help="Output filename prefix")
    ap.add_argument("--no-audio", action="store_true", help="Only write MIDI; skip WAV/MP3 rendering")
    ap.add_argument("--sample-rate", type=int, default=44100, help="WAV sample rate")
    args = ap.parse_args()

    src = Path(args.source).resolve()
    out_dir = src.parent
    mid = out_dir / f"{args.prefix}.mid"
    wav = out_dir / f"{args.prefix}.wav"
    mp3 = out_dir / f"{args.prefix}.mp3"

    build_reimagined_midi(src, mid)
    print(f"Wrote MIDI: {mid}")
    if not args.no_audio:
        render_wav(mid, wav, sr=args.sample_rate)
        print(f"Wrote WAV:  {wav}")
        try:
            if convert_mp3(wav, mp3):
                print(f"Wrote MP3:  {mp3}")
            else:
                print("MP3 skipped: ffmpeg not found")
        except Exception as exc:
            print(f"MP3 conversion failed: {exc}")

if __name__ == "__main__":
    main()
