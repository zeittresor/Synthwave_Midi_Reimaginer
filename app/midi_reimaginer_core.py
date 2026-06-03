#!/usr/bin/env python3
# source: https://github.com/zeittresor/Synthwave_Midi_Reimaginer
"""
Synthwave MIDI Reimaginer core engine.

Offline-friendly MIDI analysis + transformation + built-in audio renderer.
Does not need a Windows wavetable synth. MP3 export is optional and uses a real
ffmpeg binary only when one is detected.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from collections import defaultdict, Counter
from typing import Callable, Iterable
import argparse
import hashlib
import json
import math
import os
import random
import secrets
import shutil
import subprocess
import sys
import wave
from datetime import datetime, timezone

Progress = Callable[[str], None]


# -----------------------------
# Runtime/resource paths
# -----------------------------
def app_base_dir() -> Path:
    """Writable application base directory.

    In normal source runs this is the project folder. In a PyInstaller build it
    is the folder containing the EXE, so app_data/feedback remains persistent.
    """
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parents[1]


def app_resource_dir() -> Path:
    """Read-only app resource directory for bundled style/theme/lang data."""
    if getattr(sys, "frozen", False):
        return Path(getattr(sys, "_MEIPASS", app_base_dir())).resolve() / "app"
    return Path(__file__).resolve().parent


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


@dataclass
class Note:
    start: int
    end: int
    pitch: int
    vel: int
    ch: int
    program: int = 0
    track: int = 0
    order: int = 0

    @property
    def duration(self) -> int:
        return max(1, self.end - self.start)


@dataclass
class TrackAnalysis:
    index: int
    name: str
    notes: list[Note]
    channels: Counter
    programs: Counter
    role: str = "other"
    avg_pitch: float = 0.0
    min_pitch: int = 0
    max_pitch: int = 0
    avg_dur: float = 0.0
    avg_velocity: float = 0.0
    volume_level: float = 100.0
    density: float = 0.0
    poly_score: float = 0.0
    is_drum: bool = False
    high_problem_score: float = 0.0


@dataclass
class MidiAnalysis:
    source: Path
    fmt: int
    division: int
    track_count: int
    end_tick: int
    tempo_us: int
    bpm: float
    time_signature: tuple[int, int, int, int]
    tracks: list[TrackAnalysis]
    roles: dict[str, int | None]
    summary: str


def log(progress: Progress | None, text: str) -> None:
    if progress:
        progress(text)


def new_auto_seed() -> int:
    """Generate a fresh non-zero 31-bit seed for one render job."""
    return int(secrets.randbelow(2_147_483_646) + 1)


def normalize_seed(seed: int | str | None) -> int:
    if seed is None or str(seed).strip() == "":
        return new_auto_seed()
    value = int(seed)
    if value < 0:
        value = abs(value)
    return int(value % 2_147_483_647) or 1




# -----------------------------
# Modular style presets
# -----------------------------
STYLE_PRESET_VERSION = 4


def _styles_dir() -> Path:
    return app_resource_dir() / "styles"


def _style_json_path() -> Path:
    return _styles_dir() / "style_presets.json"


def safe_token(text: str, fallback: str = "style") -> str:
    text = (text or "").strip().lower().replace(" ", "_").replace("-", "_")
    out = []
    for ch in text:
        out.append(ch if ch.isalnum() or ch == "_" else "_")
    token = "".join(out).strip("_")
    while "__" in token:
        token = token.replace("__", "_")
    return token or fallback


def load_style_presets() -> list[dict]:
    """Load modular style presets from app/styles/style_presets.json."""
    path = _style_json_path()
    styles: list[dict] = []
    if path.exists():
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            styles = raw.get("styles", raw if isinstance(raw, list) else [])
        except Exception:
            styles = []
    cleaned: list[dict] = []
    seen: set[str] = set()
    for item in styles:
        if not isinstance(item, dict):
            continue
        sid = safe_token(str(item.get("id") or item.get("name") or "style"))
        if sid in seen:
            continue
        seen.add(sid)
        entry = dict(item)
        entry["id"] = sid
        entry.setdefault("name", sid.replace("_", " ").title())
        entry.setdefault("instruments", "synth bass, pad, lead, drum machine")
        entry.setdefault("meter", "4/4")
        entry.setdefault("info", "Generic electronic style preset.")
        entry.setdefault("bpm_min", 90)
        entry.setdefault("bpm_max", 128)
        entry.setdefault("swing", 0.04)
        entry.setdefault("drum_feel", "four_on_floor")
        entry.setdefault("bass_center", 42)
        entry.setdefault("lead_center", 68)
        entry.setdefault("arp_density", 0.60)
        entry.setdefault("pad_density", 0.70)
        entry.setdefault("brightness", 0.55)
        entry.setdefault("distortion", 0.15)
        entry.setdefault("reverb", 0.55)
        entry.setdefault("delay", 0.40)
        entry.setdefault("harmony_strictness", 0.88)
        entry.setdefault("programs", {})
        cleaned.append(entry)
    if not cleaned:
        cleaned.append({
            "id": "synthwave", "name": "Synthwave",
            "instruments": "analog synth lead, juno pad, gated snare, synth bass, arpeggiator, tom fills",
            "meter": "4/4", "info": "Fallback synthwave preset.",
            "bpm_min": 96, "bpm_max": 128, "swing": 0.05, "drum_feel": "four_on_floor",
            "bass_center": 45, "lead_center": 68, "arp_density": 0.72, "pad_density": 0.72,
            "brightness": 0.62, "distortion": 0.20, "reverb": 0.58, "delay": 0.46,
            "harmony_strictness": 0.84,
            "programs": {"bass": 38, "pluck": 5, "vibe": 11, "ticks": 115, "pad": 89, "hook": 80, "lead": 81, "echo": 88},
        })
    # Keep the GUI drop-down stable, predictable and readable. Random-style
    # resolution remains reproducible because it uses this deterministic order.
    return sorted(cleaned, key=lambda s: str(s.get("name", s.get("id", ""))).casefold())


def get_style_by_id(style_id: str | None) -> dict:
    styles = load_style_presets()
    wanted = safe_token(style_id or "synthwave")
    for style in styles:
        if style.get("id") == wanted:
            return dict(style)
    for style in styles:
        if safe_token(str(style.get("name", ""))) == wanted:
            return dict(style)
    for style in styles:
        if style.get("id") == "synthwave":
            return dict(style)
    return dict(styles[0])


def resolve_style_preset(style_id: str | None = "synthwave", *, random_style: bool = False, seed: int | None = None) -> dict:
    styles = load_style_presets()
    if random_style:
        rng = random.Random(normalize_seed(seed))
        return dict(rng.choice(styles))
    return get_style_by_id(style_id)




# -----------------------------
# Listener feedback / preference learning
# -----------------------------
FEEDBACK_PROFILE_VERSION = 1


def default_feedback_path() -> Path:
    """Default local feedback profile path. Kept outside app/ so it survives code updates if copied over."""
    return app_base_dir() / "app_data" / "feedback" / "ratings.json"


def _empty_feedback_profile() -> dict:
    return {"version": FEEDBACK_PROFILE_VERSION, "ratings": []}


def load_feedback_profile(path: Path | str | None = None) -> dict:
    path = Path(path) if path else default_feedback_path()
    if not path.exists():
        return _empty_feedback_profile()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return _empty_feedback_profile()
        data.setdefault("version", FEEDBACK_PROFILE_VERSION)
        ratings = data.get("ratings", [])
        if not isinstance(ratings, list):
            ratings = []
        data["ratings"] = [r for r in ratings if isinstance(r, dict)]
        return data
    except Exception:
        return _empty_feedback_profile()


def save_feedback_profile(profile: dict, path: Path | str | None = None) -> Path:
    path = Path(path) if path else default_feedback_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    profile = dict(profile or {})
    profile["version"] = FEEDBACK_PROFILE_VERSION
    profile.setdefault("ratings", [])
    path.write_text(json.dumps(profile, indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def reset_feedback_profile(path: Path | str | None = None) -> Path:
    return save_feedback_profile(_empty_feedback_profile(), path)


def append_feedback_rating(result: dict, rating: int, path: Path | str | None = None, note: str = "") -> dict:
    """Append a thumbs-up/thumbs-down rating for the last render result."""
    profile = load_feedback_profile(path)
    rating = 1 if int(rating) > 0 else -1
    result = dict(result or {})
    entry = {
        "time_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "rating": rating,
        "source_hash": result.get("source_hash"),
        "requested_style": result.get("requested_style") or result.get("style"),
        "style": result.get("style"),
        "style_name": result.get("style_name"),
        "seed": result.get("seed"),
        "random_style": bool(result.get("random_style")),
        "intensity": result.get("intensity"),
        "effective_intensity": result.get("effective_intensity", result.get("intensity")),
        "target_bpm": result.get("target_bpm"),
        "effective_bpm": result.get("effective_bpm", result.get("target_bpm")),
        "accompaniment_relaxation": result.get("accompaniment_relaxation", result.get("repetition")),
        "effective_accompaniment_relaxation": result.get("effective_accompaniment_relaxation", result.get("accompaniment_relaxation", result.get("repetition"))),
        "harmony_lock": result.get("harmony_lock"),
        "use_style_instruments": result.get("use_style_instruments"),
        "preserve_source_volumes": result.get("preserve_source_volumes"),
        "midi": result.get("midi"),
        "wav": result.get("wav"),
        "mp3": result.get("mp3"),
        "analysis": result.get("analysis"),
        "note": str(note or "")[:500],
    }
    profile.setdefault("ratings", []).append(entry)
    # Keep the file small enough for long-term casual use.
    profile["ratings"] = profile["ratings"][-2000:]
    save_feedback_profile(profile, path)
    return feedback_summary(profile)


def feedback_summary(profile: dict | None = None) -> dict:
    profile = profile if profile is not None else load_feedback_profile()
    ratings = [r for r in profile.get("ratings", []) if isinstance(r, dict)]
    up = sum(1 for r in ratings if int(r.get("rating", 0)) > 0)
    down = sum(1 for r in ratings if int(r.get("rating", 0)) < 0)
    by_style: dict[str, dict[str, int]] = {}
    for r in ratings:
        sid = str(r.get("style") or "unknown")
        item = by_style.setdefault(sid, {"up": 0, "down": 0})
        if int(r.get("rating", 0)) > 0:
            item["up"] += 1
        elif int(r.get("rating", 0)) < 0:
            item["down"] += 1
    best_style = None
    best_score = -10**9
    for sid, v in by_style.items():
        score = v["up"] * 2 - v["down"]
        if score > best_score:
            best_score = score
            best_style = sid
    return {"total": len(ratings), "up": up, "down": down, "by_style": by_style, "best_style": best_style}


def _rating_weight(entry: dict, style_id: str, source_hash: str | None) -> float:
    weight = 1.0
    if str(entry.get("style") or "") == str(style_id):
        weight += 2.0
    if source_hash and entry.get("source_hash") == source_hash:
        weight += 2.0
    return weight


def _weighted_avg(entries: list[tuple[dict, float]], key: str, fallback: float | None = None) -> float | None:
    total = 0.0
    acc = 0.0
    for e, w in entries:
        val = e.get(key)
        if val is None:
            continue
        try:
            f = float(val)
        except Exception:
            continue
        acc += f * w
        total += w
    if total <= 0.0:
        return fallback
    return acc / total


def compute_feedback_bias(profile: dict, style_id: str, source_hash: str | None = None) -> dict:
    """Summarize listener feedback relevant to a style/source.

    This is intentionally lightweight and deterministic. It does not train a
    model; it uses user ratings as a local preference profile.
    """
    ratings = [r for r in profile.get("ratings", []) if isinstance(r, dict)]
    relevant: list[tuple[dict, float]] = []
    positives: list[tuple[dict, float]] = []
    negatives: list[tuple[dict, float]] = []
    for r in ratings:
        w = _rating_weight(r, style_id, source_hash)
        # Far-away styles still provide a tiny global preference signal.
        if str(r.get("style") or "") != str(style_id) and (not source_hash or r.get("source_hash") != source_hash):
            w = 0.35
        val = 1 if int(r.get("rating", 0)) > 0 else -1 if int(r.get("rating", 0)) < 0 else 0
        if val == 0:
            continue
        relevant.append((r, w))
        (positives if val > 0 else negatives).append((r, w))
    pos_w = sum(w for _, w in positives)
    neg_w = sum(w for _, w in negatives)
    total_w = pos_w + neg_w
    if total_w <= 0:
        return {"enabled": False, "confidence": 0.0, "profile_count": 0}
    approval = (pos_w - neg_w) / max(0.001, total_w)
    confidence = min(0.45, 0.06 * total_w)
    # Positive ratings define the target; if there are only dislikes, reduce
    # confidence and only apply defensive smoothing.
    target_entries = positives if positives else relevant
    pref_intensity = _weighted_avg(target_entries, "effective_intensity", _weighted_avg(target_entries, "intensity", None))
    pref_bpm = _weighted_avg(target_entries, "effective_bpm", _weighted_avg(target_entries, "target_bpm", None))
    pref_relax = _weighted_avg(target_entries, "effective_accompaniment_relaxation", _weighted_avg(target_entries, "accompaniment_relaxation", None))
    pref_style_instr = _weighted_avg(target_entries, "use_style_instruments", None)
    pref_preserve_volumes = _weighted_avg(target_entries, "preserve_source_volumes", None)
    pref_harmony = _weighted_avg(target_entries, "harmony_lock", None)
    return {
        "enabled": True,
        "confidence": confidence,
        "approval": approval,
        "profile_count": len(relevant),
        "positive_weight": pos_w,
        "negative_weight": neg_w,
        "preferred_intensity": pref_intensity,
        "preferred_bpm": pref_bpm,
        "preferred_accompaniment_relaxation": pref_relax,
        "preferred_style_instruments": pref_style_instr,
        "preferred_preserve_source_volumes": pref_preserve_volumes,
        "preferred_harmony_lock": pref_harmony,
    }


def apply_feedback_preferences(
    *,
    profile: dict,
    style_preset: dict,
    source_hash: str | None,
    intensity: float,
    target_bpm: float | None,
    repetition: float,
    use_style_instruments: bool,
    preserve_source_volumes: bool,
    harmony_lock: bool,
    progress: Progress | None = None,
) -> tuple[dict, float, float | None, float, bool, bool, bool, dict]:
    style_id = str(style_preset.get("id", "synthwave"))
    bias = compute_feedback_bias(profile, style_id, source_hash)
    if not bias.get("enabled") or bias.get("confidence", 0.0) <= 0:
        return style_preset, intensity, target_bpm, repetition, use_style_instruments, preserve_source_volumes, harmony_lock, bias
    c = float(bias.get("confidence", 0.0))
    approval = float(bias.get("approval", 0.0))
    eff_intensity = float(intensity)
    eff_bpm = target_bpm
    eff_repetition = float(repetition)
    if bias.get("preferred_intensity") is not None:
        eff_intensity = mix_float(eff_intensity, float(bias["preferred_intensity"]), c * 0.30)
    if target_bpm is not None and bias.get("preferred_bpm") is not None:
        eff_bpm = mix_float(float(target_bpm), float(bias["preferred_bpm"]), c * 0.22)
    if bias.get("preferred_accompaniment_relaxation") is not None:
        eff_repetition = mix_float(eff_repetition, float(bias["preferred_accompaniment_relaxation"]), c * 0.38)
    # Only touch boolean preferences if there is a reasonably strong signal.
    eff_use_style_instr = bool(use_style_instruments)
    if bias.get("preferred_style_instruments") is not None and c > 0.18:
        p = float(bias["preferred_style_instruments"])
        if p > 0.72:
            eff_use_style_instr = True
        elif p < 0.28:
            eff_use_style_instr = False
    eff_preserve_volumes = bool(preserve_source_volumes)
    if bias.get("preferred_preserve_source_volumes") is not None and c > 0.24:
        p = float(bias["preferred_preserve_source_volumes"])
        if p > 0.76:
            eff_preserve_volumes = True
        elif p < 0.24:
            eff_preserve_volumes = False
    eff_harmony = bool(harmony_lock)
    if bias.get("preferred_harmony_lock") is not None and c > 0.22:
        p = float(bias["preferred_harmony_lock"])
        if p > 0.78:
            eff_harmony = True
        elif p < 0.22:
            eff_harmony = False
    # Defensive preset nudging: disliked profiles get less rapid accompaniment
    # and stricter harmony; liked profiles keep more of the user's preferred vibe.
    adjusted = dict(style_preset)
    if approval < -0.15:
        adjusted["arp_density"] = max(0.05, style_float(adjusted, "arp_density", 0.6) * (1.0 - min(0.35, c)))
        adjusted["pad_density"] = min(1.0, style_float(adjusted, "pad_density", 0.7) + min(0.18, c * 0.5))
        adjusted["harmony_strictness"] = min(1.0, style_float(adjusted, "harmony_strictness", 0.88) + min(0.16, c * 0.45))
    log(progress, f"Feedback learning: ON - {bias.get('profile_count', 0)} relevant rating(s), influence {c:.2f}, approval {approval:+.2f}")
    log(progress, f"Feedback effective settings: intensity {eff_intensity:.2f}, BPM {eff_bpm if eff_bpm is not None else 'auto'}, accompaniment relaxation {eff_repetition:.2f}")
    return adjusted, clamp01(eff_intensity), eff_bpm, clamp01(eff_repetition), eff_use_style_instr, eff_preserve_volumes, eff_harmony, bias


def resolve_style_preset_with_feedback(style_id: str | None = "synthwave", *, random_style: bool = False, seed: int | None = None, profile: dict | None = None) -> dict:
    """Resolve style. In random mode, feedback biases the seed-stable random choice."""
    styles = load_style_presets()
    if not random_style:
        return get_style_by_id(style_id)
    if not profile or not profile.get("ratings"):
        return resolve_style_preset(style_id, random_style=True, seed=seed)
    summary = feedback_summary(profile)
    by_style = summary.get("by_style", {}) if isinstance(summary, dict) else {}
    weighted: list[tuple[dict, float]] = []
    for st in styles:
        sid = str(st.get("id"))
        v = by_style.get(sid, {}) if isinstance(by_style, dict) else {}
        up = float(v.get("up", 0))
        down = float(v.get("down", 0))
        # Never make a style impossible; liked styles simply get more tickets.
        weight = max(0.25, 1.0 + up * 1.7 - down * 0.75)
        weighted.append((st, weight))
    rng = random.Random(normalize_seed(seed))
    total = sum(w for _, w in weighted)
    pick = rng.random() * total
    acc = 0.0
    for st, w in weighted:
        acc += w
        if pick <= acc:
            return dict(st)
    return dict(weighted[-1][0])


def style_float(style: dict, key: str, default: float, lo: float | None = None, hi: float | None = None) -> float:
    try:
        value = float(style.get(key, default))
    except Exception:
        value = float(default)
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def style_int(style: dict, key: str, default: int, lo: int | None = None, hi: int | None = None) -> int:
    try:
        value = int(round(float(style.get(key, default))))
    except Exception:
        value = int(default)
    if lo is not None:
        value = max(lo, value)
    if hi is not None:
        value = min(hi, value)
    return value


def style_program(style: dict, role: str, default: int) -> int:
    programs = style.get("programs") if isinstance(style.get("programs"), dict) else {}
    try:
        return max(0, min(127, int(programs.get(role, default))))
    except Exception:
        return default


# Stable General MIDI defaults. Style presets can override lead/melody programs
# only when the user explicitly enables the GUI option. This avoids a selected
# non-electronic style suddenly making every generated lead instrument sound
# wildly different unless requested.
STANDARD_PROGRAMS = {
    "bass": 38,     # Synth Bass 1
    "pluck": 5,    # Electric Piano 2 / plucky neutral
    "vibe": 11,    # Vibraphone
    "ticks": 115,  # Woodblock
    "pad": 89,     # Warm Pad
    "hook": 80,    # Square Lead
    "lead": 81,    # Saw Lead
    "echo": 88,    # New Age Pad
}

MELODY_PROGRAM_ROLES = {"pluck", "vibe", "ticks", "hook", "lead", "echo"}


def resolved_program(style: dict, role: str, default: int, *, use_style_instruments: bool = False) -> int:
    """Return a GM program for a generated track.

    Bass/pad follow the style by default because they are part of the arrangement
    bed. Lead/melody colors are optional so the user can keep a stable synthy
    sound while still changing rhythm/harmony/style parameters.
    """
    base = STANDARD_PROGRAMS.get(role, default)
    if role in MELODY_PROGRAM_ROLES and not use_style_instruments:
        return max(0, min(127, int(base)))
    return style_program(style, role, base)


def source_midi_hash(path: Path | str) -> str:
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def read_var(data: bytes, i: int) -> tuple[int, int]:
    value = 0
    while True:
        if i >= len(data):
            raise ValueError("Unexpected end while reading MIDI varlen value")
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
    data = Path(path).read_bytes()
    i = 0
    if data[i:i+4] != b"MThd":
        raise ValueError("Not a standard MIDI file: missing MThd")
    i += 4
    hdr_len = int.from_bytes(data[i:i+4], "big"); i += 4
    fmt = int.from_bytes(data[i:i+2], "big")
    ntr = int.from_bytes(data[i+2:i+4], "big")
    div = int.from_bytes(data[i+4:i+6], "big")
    if div & 0x8000:
        raise ValueError("SMPTE-time MIDI files are not supported by this lightweight engine yet")
    i += hdr_len
    tracks: list[Track] = []
    for ti in range(ntr):
        if i + 8 > len(data) or data[i:i+4] != b"MTrk":
            raise ValueError(f"Missing MTrk chunk at track {ti}")
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
                        raise ValueError("Running status byte without prior status")
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
            tick = max(0, int(round(ev.abs_tick)))
            dt = max(0, tick - prev)
            prev += dt
            body += write_var(dt) + event_raw(ev)
            if ev.type == "meta" and ev.meta_type == 0x2F:
                has_end = True
        if not has_end:
            body += write_var(0) + b"\xFF\x2F\x00"
        out += b"MTrk" + len(body).to_bytes(4,"big") + body
    Path(path).write_bytes(out)


def make_meta(abs_tick: int, meta_type: int, data: bytes, order: int = 0) -> Event:
    return Event(int(abs_tick), 0, "meta", None, None, bytes(data), meta_type, order=order)


def make_midi(abs_tick: int, status: int, data: list[int] | bytes, order: int = 10) -> Event:
    hi = status & 0xF0
    typ = {0x80:"note_off",0x90:"note_on",0xA0:"poly_aftertouch",0xB0:"control_change",0xC0:"program_change",0xD0:"channel_aftertouch",0xE0:"pitch_bend"}.get(hi,"midi")
    return Event(int(abs_tick), 0, typ, status, status & 0x0F, bytes(int(x) & 0xFF for x in data), order=order)


def clip(v, lo, hi):
    return max(lo, min(hi, int(round(v))))


def quantize_tick(t: int, grid: int) -> int:
    grid = max(1, int(grid))
    return int(round(t / grid) * grid)


def add_note(evs: list[Event], ch: int, pitch: int, start: int, duration: int, vel: int = 90, order_on: int = 30):
    pitch = clip(pitch, 0, 127)
    start = max(0, int(round(start)))
    dur = max(8, int(round(duration)))
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


def extract_notes_from_track(track: Track, track_index: int, song_end: int) -> list[Note]:
    stacks = defaultdict(list)
    notes: list[Note] = []
    order = 0
    current_program = defaultdict(lambda: 0)
    for e in track.events:
        if e.status is None or e.channel is None:
            order += 1
            continue
        hi = e.status & 0xF0
        ch = e.channel
        if hi == 0xC0 and e.data:
            current_program[ch] = e.data[0]
        elif hi == 0x90 and len(e.data) >= 2 and e.data[1] > 0:
            stacks[(ch, e.data[0])].append((e.abs_tick, e.data[1], current_program[ch], order))
        elif (hi == 0x80 and len(e.data) >= 2) or (hi == 0x90 and len(e.data) >= 2 and e.data[1] == 0):
            key = (ch, e.data[0])
            if stacks[key]:
                st, vel, prog, o = stacks[key].pop(0)
                if e.abs_tick > st:
                    notes.append(Note(st, e.abs_tick, e.data[0], vel, ch, prog, track_index, o))
        order += 1
    for (ch, pitch), qs in stacks.items():
        for st, vel, prog, o in qs:
            notes.append(Note(st, min(st + 384, song_end), pitch, vel, ch, prog, track_index, o))
    notes.sort(key=lambda n: (n.start, n.pitch, n.order))
    return notes


def get_tempo_and_sig(tracks: list[Track]) -> tuple[int, tuple[int, int, int, int]]:
    tempo = 500000
    sig = (4, 2, 24, 8)
    for t in tracks:
        for e in t.events:
            if e.type == "meta" and e.meta_type == 0x51 and len(e.data) == 3:
                tempo = int.from_bytes(e.data, "big")
                return tempo, sig
            if e.type == "meta" and e.meta_type == 0x58 and len(e.data) >= 4:
                sig = tuple(e.data[:4])  # type: ignore[assignment]
    return tempo, sig


def estimate_track_volume_level(track: Track, notes: list[Note]) -> tuple[float, float]:
    """Estimate a track's source loudness from MIDI CC7 and note velocities.

    This is intentionally simple and offline-safe. It lets generated replacement
    instruments stay close to the perceived level of the source track when the
    user enables the preserve-volume option.
    """
    cc7_values: list[int] = []
    for e in track.events:
        if e.status is not None and e.channel is not None and (e.status & 0xF0) == 0xB0 and len(e.data) >= 2:
            if int(e.data[0]) == 7:
                cc7_values.append(int(e.data[1]))
    cc7_level = float(sum(cc7_values) / len(cc7_values)) if cc7_values else 100.0
    avg_velocity = float(sum(n.vel for n in notes) / len(notes)) if notes else 90.0
    combined = float(clip(0.55 * cc7_level + 0.45 * avg_velocity, 16, 127))
    return avg_velocity, combined


def estimate_poly_score(notes: list[Note]) -> float:
    if not notes:
        return 0.0
    starts = Counter(quantize_tick(n.start, 24) for n in notes)
    simultaneous = sum(1 for c in starts.values() if c >= 2)
    return simultaneous / max(1, len(starts))


def classify_tracks(source: Path, fmt: int, div: int, tracks: list[Track], progress: Progress | None = None) -> MidiAnalysis:
    log(progress, f"[32%] Parsed {len(tracks)} track(s). Extracting notes...")
    end_tick = max([0] + [e.abs_tick for t in tracks for e in t.events])
    tempo_us, sig = get_tempo_and_sig(tracks)
    bpm = 60_000_000 / tempo_us if tempo_us else 120.0
    analyses: list[TrackAnalysis] = []
    total_tracks = max(1, len(tracks))
    for idx, t in enumerate(tracks):
        pct = 35 + int(45 * (idx + 1) / total_tracks)
        log(progress, f"[{pct}%] Analyzing track {idx + 1}/{len(tracks)}: {t.name or f'Track {idx}'}")
        notes = extract_notes_from_track(t, idx, end_tick)
        if notes:
            pitches = [n.pitch for n in notes]
            durations = [n.duration for n in notes]
            chs = Counter(n.ch for n in notes)
            progs = Counter(n.program for n in notes)
            avg_velocity, volume_level = estimate_track_volume_level(t, notes)
            ta = TrackAnalysis(
                index=idx, name=t.name or f"Track {idx}", notes=notes, channels=chs, programs=progs,
                avg_pitch=sum(pitches) / len(pitches), min_pitch=min(pitches), max_pitch=max(pitches),
                avg_dur=sum(durations) / len(durations), avg_velocity=avg_velocity, volume_level=volume_level, density=len(notes) / max(1, end_tick / div),
                poly_score=estimate_poly_score(notes), is_drum=(chs.most_common(1)[0][0] == 9),
            )
            high_count = sum(1 for p in pitches if p >= 88)
            ta.high_problem_score = (high_count / len(pitches)) * 2.0 + max(0.0, (ta.max_pitch - 92) / 20.0)
        else:
            ta = TrackAnalysis(idx, t.name or f"Track {idx}", [], Counter(), Counter())
        analyses.append(ta)

    log(progress, "[84%] Detecting musical roles and problem tracks...")
    melodic = [a for a in analyses if a.notes and not a.is_drum]
    drums = [a for a in analyses if a.notes and a.is_drum]
    roles: dict[str, int | None] = {"bass": None, "lead": None, "hook_problem": None, "arp": None, "pad_source": None, "drums": None}
    if drums:
        roles["drums"] = max(drums, key=lambda a: len(a.notes)).index
    if melodic:
        bass = min(melodic, key=lambda a: (a.avg_pitch + (0 if a.min_pitch < 52 else 18), -len(a.notes)))
        roles["bass"] = bass.index
        for a in melodic:
            if a.index == bass.index:
                a.role = "bass"
        high = max(melodic, key=lambda a: (a.high_problem_score, a.max_pitch, a.avg_pitch))
        if high.high_problem_score > 0.10 or high.max_pitch >= 88:
            roles["hook_problem"] = high.index
            if analyses[high.index].role == "other":
                analyses[high.index].role = "high/problem-hook"
        lead_candidates = [a for a in melodic if a.index != roles["bass"]]
        if lead_candidates:
            # Lead should usually be a real melodic contour, not merely the highest tiny squeak track.
            # The high/problem track is still used for the de-squeaked hook role separately.
            lead = max(
                lead_candidates,
                key=lambda a: (
                    min(len(a.notes), 500) * 0.020
                    + a.density * 2.0
                    + a.avg_pitch / 50.0
                    - a.high_problem_score * 1.8
                    - (4.0 if a.avg_pitch > 92 else 0.0)
                    - (2.0 if (a.programs and a.programs.most_common(1)[0][0] >= 112) else 0.0)
                    - (2.0 if len(a.notes) < 24 else 0.0)
                )
            )
            roles["lead"] = lead.index
            if analyses[lead.index].role == "other":
                analyses[lead.index].role = "lead"
            arp = max(lead_candidates, key=lambda a: (a.density, -a.avg_dur, len(a.notes) * 0.01))
            roles["arp"] = arp.index
            if analyses[arp.index].role == "other":
                analyses[arp.index].role = "arp/pluck"
            pad_candidates = [a for a in lead_candidates if a.index != roles.get("hook_problem")] or lead_candidates
            pad = max(pad_candidates, key=lambda a: (a.poly_score * 4.0 + a.avg_dur / max(1, div) - a.density * 0.1 + min(len(a.notes), 200) * 0.002))
            roles["pad_source"] = pad.index
            if analyses[pad.index].role == "other":
                analyses[pad.index].role = "chord/pad-source"
    for a in analyses:
        if a.is_drum:
            a.role = "drums"
        elif a.role == "other" and a.notes:
            if a.avg_pitch < 58:
                a.role = "low support"
            elif a.density > 4.0:
                a.role = "busy texture"
            else:
                a.role = "melodic source"

    log(progress, "[94%] Building analysis summary...")

    lines = [
        f"Format {fmt}, {len(tracks)} tracks, PPQ {div}, length {end_tick} ticks, approx. {bpm:.1f} BPM.",
        "Detected roles:",
    ]
    for k, v in roles.items():
        if v is not None:
            lines.append(f"  - {k}: Track {v} ({analyses[v].name})")
    lines.append("\nTrack details:")
    for a in analyses:
        if not a.notes:
            lines.append(f"  #{a.index:02d} {a.name}: no notes")
        else:
            lines.append(
                f"  #{a.index:02d} {a.name}: {len(a.notes)} notes, role={a.role}, "
                f"pitch {a.min_pitch}-{a.max_pitch}, avg {a.avg_pitch:.1f}, density {a.density:.2f}/quarter, "
                f"avg velocity {a.avg_velocity:.1f}, source volume {a.volume_level:.1f}"
            )
    return MidiAnalysis(source, fmt, div, len(tracks), end_tick, tempo_us, bpm, sig, analyses, roles, "\n".join(lines))


def analyze_midi(path: Path | str, progress: Progress | None = None) -> MidiAnalysis:
    p = Path(path)
    log(progress, f"[5%] Reading MIDI file: {p.name}")
    fmt, ntr, div, tracks = parse_midi(p)
    log(progress, f"[28%] MIDI parsed: format {fmt}, {ntr} track(s), PPQ {div}")
    analysis = classify_tracks(p, fmt, div, tracks, progress=progress)
    log(progress, "[100%] Analysis finished.")
    return analysis


def notes_for_role(analysis: MidiAnalysis, role: str) -> list[Note]:
    idx = analysis.roles.get(role)
    if idx is None or idx >= len(analysis.tracks):
        return []
    return analysis.tracks[idx].notes


def source_volume_level_for_role(analysis: MidiAnalysis, role: str, default: float = 100.0) -> float:
    """Return an estimated source volume for a musical role.

    Role fallbacks intentionally map generated replacement tracks to the closest
    source material, so changed instruments can still keep the original track
    balance when requested.
    """
    fallback_roles = {
        "bass": ["bass"],
        "drums": ["drums"],
        "lead": ["lead", "hook_problem", "pad_source"],
        "hook": ["hook_problem", "lead", "arp"],
        "pluck": ["arp", "lead", "pad_source"],
        "vibe": ["arp", "pad_source", "lead"],
        "ticks": ["arp", "hook_problem", "lead"],
        "pad": ["pad_source", "lead", "arp"],
        "relief": ["pad_source", "lead"],
        "echo": ["lead", "arp", "pad_source"],
    }
    for r in fallback_roles.get(role, [role]):
        idx = analysis.roles.get(r)
        if idx is not None and 0 <= idx < len(analysis.tracks):
            tr = analysis.tracks[idx]
            if tr.notes:
                return float(tr.volume_level or default)
    # Fallback to the average melodic/drum level rather than a fixed loudness.
    levels = [float(t.volume_level) for t in analysis.tracks if t.notes and (not t.is_drum or role == "drums")]
    if levels:
        return float(sum(levels) / len(levels))
    return float(default)


def source_preserved_volume(analysis: MidiAnalysis, role: str, base_volume: float, preserve: bool) -> int:
    if not preserve:
        return clip(base_volume, 0, 127)
    source_level = source_volume_level_for_role(analysis, role, default=base_volume)
    # Strongly favor source level, but retain a little style balance so the mix
    # does not collapse when a very quiet source track is mapped to a lead role.
    return clip(mix_float(base_volume, source_level, 0.82), 12, 127)


def all_melodic_notes(analysis: MidiAnalysis) -> list[Note]:
    notes: list[Note] = []
    for t in analysis.tracks:
        if t.notes and not t.is_drum:
            notes.extend(t.notes)
    return sorted(notes, key=lambda n: (n.start, n.pitch))


def pitch_into_range(p: int, lo: int, hi: int) -> int:
    p = int(p)
    while p > hi:
        p -= 12
    while p < lo:
        p += 12
    return clip(p, lo, hi)


def closest_scale_pc(pc: int, scale: list[int]) -> int:
    return min(scale, key=lambda x: min((x-pc) % 12, (pc-x) % 12))


MODE_INTERVALS = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
}

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def mode_scale(tonic: int, mode: str = "minor") -> list[int]:
    intervals = MODE_INTERVALS.get(mode, MODE_INTERVALS["minor"])
    return [((tonic + i) % 12) for i in intervals]


def _weighted_pitch_classes(analysis: MidiAnalysis) -> Counter:
    weights = Counter()
    bass_idx = analysis.roles.get("bass")
    hook_problem_idx = analysis.roles.get("hook_problem")
    for tr in analysis.tracks:
        if tr.is_drum or not tr.notes:
            continue
        role_weight = 1.0
        if tr.index == bass_idx or tr.role == "bass":
            role_weight = 4.2
        elif tr.index == hook_problem_idx:
            # Problem-hook tracks are often tiny, squeaky ornaments. They should not define the key.
            role_weight = 0.25
        elif tr.avg_pitch > 90:
            role_weight = 0.35
        elif tr.role in ("chord/pad-source", "low support"):
            role_weight = 1.6
        for n in tr.notes:
            dur = max(1, n.duration)
            # Lower voices usually carry harmony; give them more voting power.
            low_boost = 1.0 + max(0, 72 - n.pitch) / 48.0
            weights[n.pitch % 12] += dur * role_weight * low_boost
    return weights


def detect_key_and_mode(analysis: MidiAnalysis) -> tuple[int, str, list[int], float]:
    """Return tonic, mode, ordered scale pitch classes and a soft confidence score.

    The generated arrangement uses this as a hard safety rail. Earlier versions
    used the seven most common pitch classes in frequency order, which was enough
    for analysis but wrong for building triads; degree indexing on an unordered
    scale can create unrelated pad chords and therefore obvious clashes.
    """
    weights = _weighted_pitch_classes(analysis)
    if not weights:
        return 0, "minor", mode_scale(0, "minor"), 0.0

    # Krumhansl-ish profiles. Good enough for MIDI clean-up and deterministic offline use.
    profiles = {
        "major": [6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88],
        "minor": [6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17],
    }
    scores: list[tuple[float, int, str]] = []
    for mode, profile in profiles.items():
        for tonic in range(12):
            score = 0.0
            for pc, w in weights.items():
                # profile index 0 is tonic, so rotate the input pc into the candidate key.
                score += float(w) * profile[(pc - tonic) % 12]
            # Mild synthwave/default preference for minor unless major is clearly better.
            if mode == "minor":
                score *= 1.025
            scores.append((score, tonic, mode))
    scores.sort(reverse=True)
    best, tonic, mode = scores[0]
    second = scores[1][0] if len(scores) > 1 else best
    confidence = (best - second) / max(best, 1.0)
    return tonic, mode, mode_scale(tonic, mode), confidence


def snap_pitch_to_scale(pitch: int, scale: list[int], *, prefer_down: bool = False) -> int:
    pitch = int(round(pitch))
    candidates = []
    for delta in range(-6, 7):
        p = pitch + delta
        if 0 <= p <= 127 and (p % 12) in scale:
            candidates.append(p)
    if not candidates:
        return pitch
    if prefer_down:
        return min(candidates, key=lambda p: (abs(p - pitch), 0 if p <= pitch else 1))
    return min(candidates, key=lambda p: (abs(p - pitch), abs((p % 12) - (pitch % 12))))


def scale_degree_index(pc: int, scale: list[int]) -> int:
    pc = pc % 12
    if pc in scale:
        return scale.index(pc)
    return scale.index(closest_scale_pc(pc, scale))


def chord_tones_for_root(root: int, scale: list[int], seventh: bool = False) -> list[int]:
    i = scale_degree_index(root, scale)
    tones = [scale[i], scale[(i + 2) % len(scale)], scale[(i + 4) % len(scale)]]
    if seventh and len(scale) >= 7:
        tones.append(scale[(i + 6) % len(scale)])
    return tones


def active_root_for_tick(tick: int, roots: list[tuple[int, int]]) -> int:
    if not roots:
        return 0
    current = roots[0][1]
    for st, root in roots:
        if st <= tick:
            current = root
        else:
            break
    return current


def snap_pitch_to_chord_or_scale(
    pitch: int,
    tick: int,
    roots: list[tuple[int, int]],
    scale: list[int],
    *,
    chord_bias: float = 0.55,
    prefer_down: bool = False,
) -> int:
    """Quantize a copied source pitch so it does not fight the generated pads.

    First snap to the global scale. If the pitch still sits far away from the
    active chord, pull it to a nearby chord tone. Short arps can use lower
    chord_bias, long leads/pads should use higher chord_bias.
    """
    p = snap_pitch_to_scale(pitch, scale, prefer_down=prefer_down)
    root = active_root_for_tick(tick, roots)
    chord = chord_tones_for_root(root, scale, seventh=True)
    if (p % 12) in chord:
        return p
    candidates = []
    for pc in chord:
        for octave in range(1, 10):
            q = pc + 12 * octave
            if 0 <= q <= 127:
                candidates.append(q)
    if not candidates:
        return p
    q = min(candidates, key=lambda x: abs(x - p))
    # Pull stronger for long notes and high-volume lead lines, weaker for decorative fast notes.
    if abs(q - p) <= (2 + int(4 * chord_bias)):
        return q
    return p


def sanitize_copied_pitch(
    pitch: int,
    lo: int,
    hi: int,
    tick: int,
    roots: list[tuple[int, int]],
    scale: list[int],
    *,
    chord_bias: float = 0.45,
) -> int:
    p = pitch_into_range(pitch, lo, hi)
    p = snap_pitch_to_chord_or_scale(p, tick, roots, scale, chord_bias=chord_bias, prefer_down=(p > hi - 4))
    return pitch_into_range(p, lo, hi)


def derive_roots(analysis: MidiAnalysis, bar: int, scale_hint: list[int] | None = None) -> list[tuple[int, int]]:
    bass_notes = notes_for_role(analysis, "bass")
    pool = bass_notes if bass_notes else all_melodic_notes(analysis)
    if not pool:
        pool = [Note(0, analysis.end_tick, 48, 90, 1)]
    roots: list[tuple[int, int]] = []
    if scale_hint is None:
        # Build a compact source pitch-class palette.
        pc_counter = Counter(n.pitch % 12 for n in all_melodic_notes(analysis))
        common = [pc for pc, _ in pc_counter.most_common(7)]
        scale_hint = common if len(common) >= 5 else [0, 2, 3, 5, 7, 8, 10]
    for st in range(0, max(bar, analysis.end_tick), bar * 2):
        c = Counter()
        for n in pool:
            if st <= n.start < st + bar * 2:
                c[n.pitch % 12] += n.duration
        root = c.most_common(1)[0][0] if c else (roots[-1][1] if roots else scale_hint[0])
        root = closest_scale_pc(root, scale_hint)
        roots.append((st, root))
    return roots


def nearest_pitch(pc: int, center: int) -> int:
    candidates = [pc + 12*o for o in range(1, 10)]
    return min(candidates, key=lambda p: abs(p-center))



def clamp01(value: float) -> float:
    try:
        x = float(value)
    except Exception:
        x = 0.0
    return max(0.0, min(1.0, x))


def smoothstep01(value: float) -> float:
    x = clamp01(value)
    return x * x * (3.0 - 2.0 * x)


def mix_float(a: float, b: float, t: float) -> float:
    t = clamp01(t)
    return float(a) * (1.0 - t) + float(b) * t


def seeded_rng(seed: int, label: str) -> random.Random:
    digest = hashlib.sha256(f"{int(seed)}:{label}".encode("utf-8")).digest()
    return random.Random(int.from_bytes(digest[:8], "big"))


def choose_from_scale_degree(root: int, scale: list[int], degree_offset: int, center: int) -> int:
    if not scale:
        return int(center)
    i = scale_degree_index(root, scale)
    pc = scale[(i + degree_offset) % len(scale)]
    return nearest_pitch(pc, center)


def maybe_mutate_pitch(
    pitch: int,
    tick: int,
    lo: int,
    hi: int,
    roots: list[tuple[int, int]],
    scale: list[int],
    rng: random.Random,
    rewrite: float,
    *,
    chord_bias: float = 0.70,
) -> int:
    """Seed-dependent but harmony-safe pitch mutation.

    At low intensity this does almost nothing. At high intensity it replaces many
    copied source tones with nearby scale/chord degrees, which makes the seed
    affect the actual melody rather than only tiny ornaments.
    """
    p = pitch_into_range(pitch, lo, hi)
    if rng.random() < 0.74 * clamp01(rewrite):
        root = active_root_for_tick(tick, roots)
        degree = rng.choice([-2, -1, 0, 1, 2, 3, 4, 5])
        center = (lo + hi) // 2 + rng.choice([-5, -2, 0, 2, 5])
        p = choose_from_scale_degree(root, scale, degree, center)
    return sanitize_copied_pitch(p, lo, hi, tick, roots, scale, chord_bias=chord_bias)



def de_repeat_pitch_or_skip(
    state: dict[str, tuple[int, int]],
    role: str,
    pitch: int,
    tick: int,
    lo: int,
    hi: int,
    roots: list[tuple[int, int]],
    scale: list[int],
    rng: random.Random,
    repetition: float,
    rewrite: float,
) -> int | None:
    """Reduce annoying long runs of the same pitch.

    repetition=1.0 preserves/encourages looping. repetition=0.0 allows only
    short repeated runs, then either skips the note or moves it to a nearby
    scale/chord tone. This is deliberately deterministic from the seed because
    the same seed must reproduce the same anti-monotony decisions.
    """
    repetition = clamp01(repetition)
    if repetition >= 0.985:
        return pitch_into_range(pitch, lo, hi)
    p = pitch_into_range(pitch, lo, hi)
    last_pitch, run_len = state.get(role, (-999, 0))
    same = (p == last_pitch) or ((p % 12) == (last_pitch % 12) and abs(p - last_pitch) <= 12)
    run_len = run_len + 1 if same else 1
    allowed = 1 + int(round(repetition * 8.0))
    if same and run_len > allowed:
        pressure = clamp01((run_len - allowed) / 6.0)
        change_prob = clamp01((1.0 - repetition) * (0.55 + 0.35 * rewrite + 0.25 * pressure))
        skip_prob = clamp01((1.0 - repetition) * (0.18 + 0.24 * pressure) * (0.5 + 0.5 * rewrite))
        if rng.random() < skip_prob:
            state[role] = (last_pitch, run_len)
            return None
        if rng.random() < change_prob:
            root = active_root_for_tick(tick, roots)
            current_degree = scale_degree_index(p % 12, scale) if scale else 0
            offset = rng.choice([-3, -2, -1, 1, 2, 3])
            p = choose_from_scale_degree(root, scale, current_degree + offset, (lo + hi) // 2 + rng.choice([-7, -3, 0, 3, 7]))
            p = pitch_into_range(p, lo, hi)
            run_len = 1
    state[role] = (p, run_len)
    return p


def add_note_controlled(
    evs: list[Event],
    ch: int,
    pitch: int,
    start: int,
    duration: int,
    vel: int,
    *,
    state: dict[str, tuple[int, int]],
    role: str,
    lo: int,
    hi: int,
    roots: list[tuple[int, int]],
    scale: list[int],
    rng: random.Random,
    repetition: float,
    rewrite: float,
) -> bool:
    p = de_repeat_pitch_or_skip(state, role, pitch, start, lo, hi, roots, scale, rng, repetition, rewrite)
    if p is None:
        return False
    add_note(evs, ch, p, start, duration, vel)
    return True


def build_reimagined_midi(
    src: Path | str,
    out_mid: Path | str,
    *,
    style: str = "synthwave",
    style_preset: dict | None = None,
    intensity: float = 0.65,
    target_bpm: float | None = None,
    repetition: float = 0.50,
    use_style_instruments: bool = False,
    preserve_source_volumes: bool = False,
    preserve_length: bool = True,
    harmony_lock: bool = True,
    seed: int | None = None,
    progress: Progress | None = None,
) -> tuple[Path, MidiAnalysis]:
    src = Path(src)
    out_mid = Path(out_mid)
    seed = normalize_seed(seed)
    intensity = clamp01(intensity)
    repetition = clamp01(repetition)
    accomp_relaxation = repetition
    pulse_amount = 1.0 - accomp_relaxation

    # v0.2.2+: make the slider musically meaningful.
    # 0.0 = close to source / cleaned copy, 1.0 = mostly regenerated arrangement in the selected style.
    rewrite = smoothstep01(intensity)
    source_keep = 1.0 - rewrite
    strong_rewrite = rewrite ** 1.35

    master_rng = random.Random(seed)
    rng_bass = seeded_rng(seed, "bass")
    rng_arp = seeded_rng(seed, "arp")
    rng_pad = seeded_rng(seed, "pad")
    rng_hook = seeded_rng(seed, "hook")
    rng_lead = seeded_rng(seed, "lead")
    rng_drum = seeded_rng(seed, "drums")
    rng_echo = seeded_rng(seed, "echo")
    rng_relief = seeded_rng(seed, "relief")
    variant = master_rng.randrange(128)
    variant4 = variant % 4

    style_preset = dict(style_preset or get_style_by_id(style))
    style_id = style_preset.get("id", safe_token(style))
    style_name = str(style_preset.get("name", style_id))
    style_slug = safe_token(style_id)
    log(progress, f"Analysiere MIDI: {src.name}")
    log(progress, f"Generation seed: {seed} / arrangement variant {variant}")
    log(progress, f"Transformation intensity: {intensity:.2f} (source keep {source_keep:.2f}, rewrite {rewrite:.2f})")
    log(progress, f"Accompaniment relaxation: {accomp_relaxation:.2f} (0=dense pulses, 1=sparser/pad relief)")
    log(progress, f"Style preset: {style_name} ({style_slug})")
    log(progress, f"Style lead/melody instruments: {'ON' if use_style_instruments else 'OFF'}")
    log(progress, f"Preserve source track volumes: {'ON' if preserve_source_volumes else 'OFF'}")
    analysis = analyze_midi(src, progress=progress)
    div = analysis.division
    bar = div * 4
    song_end = analysis.end_tick if preserve_length else min(analysis.end_tick, 96 * bar)
    song_end = max(song_end, 8 * bar)

    def role_volume(role: str, base_volume: float) -> int:
        return source_preserved_volume(analysis, role, base_volume, preserve_source_volumes)

    if preserve_source_volumes:
        volume_bits = []
        for role in ("bass", "lead", "hook", "pluck", "pad", "drums"):
            volume_bits.append(f"{role}={source_volume_level_for_role(analysis, role):.1f}")
        log(progress, "Source volume profile: " + ", ".join(volume_bits))

    # Tempo now follows the slider. 0% stays very close to source BPM, 100% follows the style BPM window.
    bpm_min = style_float(style_preset, "bpm_min", 88.0, 40.0, 220.0)
    bpm_max = style_float(style_preset, "bpm_max", 132.0, bpm_min + 1.0, 240.0)
    style_mid_bpm = (bpm_min + bpm_max) / 2.0
    tempo_jitter = master_rng.uniform(-4.0, 4.0) * rewrite
    if target_bpm is not None:
        try:
            target_bpm_value = max(40.0, min(240.0, float(target_bpm)))
        except Exception:
            target_bpm_value = style_mid_bpm
        bpm_source = "user slider"
    else:
        target_bpm_value = mix_float(analysis.bpm, style_mid_bpm, rewrite)
        if rewrite > 0.98:
            target_bpm_value += master_rng.uniform(bpm_min - style_mid_bpm, bpm_max - style_mid_bpm) * 0.35
        target_bpm_value = max(bpm_min if rewrite > 0.55 else 40.0, min(bpm_max if rewrite > 0.55 else 240.0, target_bpm_value + tempo_jitter))
        bpm_source = "source/style/seed"
    tempo = int(round(60_000_000 / target_bpm_value))
    log(progress, f"Erzeuge neue {style_name}-Version bei ca. {target_bpm_value:.1f} BPM ({bpm_source})")

    # Style parameters are applied gradually by intensity.
    swing_amount = style_float(style_preset, "swing", 0.04, 0.0, 0.25) * (0.10 + 0.90 * rewrite)
    arp_density = style_float(style_preset, "arp_density", 0.60, 0.0, 1.0)
    pad_density = style_float(style_preset, "pad_density", 0.70, 0.0, 1.0)
    harmony_strictness = style_float(style_preset, "harmony_strictness", 0.88, 0.0, 1.0)
    brightness = style_float(style_preset, "brightness", 0.55, 0.0, 1.0)
    distortion = style_float(style_preset, "distortion", 0.15, 0.0, 1.0)
    reverb_amount = style_float(style_preset, "reverb", 0.55, 0.0, 1.0)
    delay_amount = style_float(style_preset, "delay", 0.40, 0.0, 1.0)
    drum_feel = str(style_preset.get("drum_feel", "four_on_floor"))
    bass_center = style_int(style_preset, "bass_center", 42, 28, 58)
    lead_center = style_int(style_preset, "lead_center", 68, 52, 84)
    bass_lo, bass_hi = max(24, bass_center - 8), min(64, bass_center + 10)
    lead_lo, lead_hi = max(45, lead_center - 11), min(91, lead_center + 13)
    hook_lo, hook_hi = max(48, lead_center - 9), min(88, lead_center + 10)
    arp_lo, arp_hi = max(45, lead_center - 16), min(88, lead_center + 10)
    pad_center = max(45, min(68, bass_center + 16))

    all_notes = all_melodic_notes(analysis)
    tonic, mode, scale, key_confidence = detect_key_and_mode(analysis)
    log(progress, f"Harmony lock: {'ON' if harmony_lock else 'OFF'} - detected {NOTE_NAMES[tonic]} {mode} (confidence {key_confidence:.2f}, strictness {harmony_strictness:.2f})")

    roots = derive_roots(analysis, bar, scale)
    # At high intensity the seed is allowed to re-order some root movement, but it stays in key.
    if rewrite > 0.72 and len(roots) > 4:
        rewritten_roots: list[tuple[int, int]] = []
        degree_templates = [[0, 5, 3, 6], [0, 2, 5, 4], [0, 6, 3, 4], [0, 4, 5, 3], [0, 3, 5, 6]]
        tmpl = rng_pad.choice(degree_templates)
        base_root = roots[0][1]
        base_idx = scale_degree_index(base_root, scale)
        for ri, (st, root) in enumerate(roots):
            if rng_pad.random() < (rewrite - 0.62) * 1.7:
                root = scale[(base_idx + tmpl[(ri + variant) % len(tmpl)]) % len(scale)]
            rewritten_roots.append((st, root))
        roots = rewritten_roots

    pluck_phase = rng_arp.randrange(16)
    vibe_offset = rng_lead.randrange(3)
    tick_phase = rng_arp.randrange(8)
    hook_transpose = rng_hook.choice([-12, 0, 0, 0, 12]) if intensity > 0.55 else 0
    hat_swing = int(div * swing_amount) if swing_amount > 0 else 0
    fill_variant = rng_drum.randrange(8)
    copy_grid = div // 8 if intensity < 0.25 else div // 4
    # The repetition slider was repurposed in v0.2.7: it now controls accompaniment relaxation.
    # 0.0 = active/rhythmic accompaniment, 1.0 = fewer rapid note attacks plus more pad/string relief.
    source_note_probability = max(0.04, (1.0 - 0.88 * rewrite) * mix_float(1.0, 0.68, accomp_relaxation))
    accomp_gate = mix_float(1.0, 0.28, accomp_relaxation)
    pulse_gate = mix_float(1.0, 0.18, accomp_relaxation)
    repeat_state: dict[str, tuple[int, int]] = {}

    def add_mel(evs: list[Event], ch: int, pitch: int, start: int, duration: int, vel: int, role: str, lo: int, hi: int, rng: random.Random) -> bool:
        # Pitch de-repetition is strongest for accompaniment roles when the
        # relaxation slider is moved right. Bass and main hooks remain more
        # stable so the musical identity does not disappear.
        if role in {"pluck", "ticks", "vibe", "vibe_relief", "hook_answer", "lead_fill", "echo"}:
            role_repetition = max(0.02, 1.0 - accomp_relaxation)
        elif role in {"lead", "hook"}:
            role_repetition = max(0.18, 1.0 - 0.55 * accomp_relaxation)
        else:
            role_repetition = max(0.25, 1.0 - 0.35 * accomp_relaxation)
        return add_note_controlled(
            evs, ch, pitch, start, duration, vel,
            state=repeat_state, role=role, lo=lo, hi=hi, roots=roots, scale=scale,
            rng=rng, repetition=role_repetition, rewrite=rewrite,
        )

    new_tracks: list[list[Event]] = []
    meta = [
        make_meta(0, 0x03, f"Synthwave MIDI Reimaginer GUI - {style_name}".encode("latin1", errors="replace"), order=0),
        make_meta(0, 0x01, f"Seed: {seed}; Style: {style_slug}; Variant: {variant}; Intensity: {intensity:.2f}; Rewrite: {rewrite:.2f}; BPM: {target_bpm_value:.1f}; Accompaniment relaxation: {accomp_relaxation:.2f}; Harmony lock: {'ON' if harmony_lock else 'OFF'}".encode("latin1", errors="replace"), order=1),
        make_meta(0, 0x51, tempo.to_bytes(3, "big"), order=2),
        make_meta(0, 0x58, bytes(analysis.time_signature), order=3),
    ]
    for b, label in [(0,b"INTRO"),(8,b"GROOVE"),(24,b"HOOK"),(48,b"CHORUS"),(64,b"ALT"),(80,b"OUTRO")]:
        if b * bar < song_end:
            meta.append(make_meta(b * bar, 0x06, label, order=4))
    meta.append(make_meta(song_end, 0x2F, b"", order=99))
    new_tracks.append(meta)

    # -----------------------------
    # Bass: source-copy at low intensity, generated bassline at high intensity.
    # -----------------------------
    bass_src = notes_for_role(analysis, "bass") or [n for n in all_notes if n.pitch < 60] or all_notes[:]
    if not bass_src:
        bass_src = [Note(0, song_end, 48, 90, 1)]
    bass = setup_track(f"{style_name.upper()} BASS", ch=1, program=resolved_program(style_preset, "bass", 38, use_style_instruments=True), volume=role_volume("bass", 104 + distortion * 20), pan=48, reverb=int(8 + reverb_amount * 24), chorus=int(14 + brightness * 18))
    for n in bass_src:
        if n.start >= song_end:
            continue
        if rng_bass.random() > (0.95 if intensity < 0.08 else source_note_probability):
            continue
        st = quantize_tick(n.start, copy_grid)
        dur = max(div // 8, quantize_tick(n.duration, div // 8))
        p = pitch_into_range(n.pitch, bass_lo, bass_hi)
        if harmony_lock:
            p = sanitize_copied_pitch(p, bass_lo, bass_hi, st, roots, scale, chord_bias=max(0.75, harmony_strictness))
        if rewrite > 0.35:
            p = maybe_mutate_pitch(p, st, bass_lo, bass_hi, roots, scale, rng_bass, rewrite * 0.55, chord_bias=max(0.80, harmony_strictness))
        add_mel(bass, 1, p, st, min(int(dur * mix_float(0.95, 0.66, rewrite)), song_end - st), n.vel * mix_float(0.90, 0.48, rewrite), "bass", bass_lo, bass_hi, rng_bass)
    if rewrite > 0.10:
        bass_patterns = [
            [0, div, 2*div, 3*div],
            [0, div//2, div + div//2, 2*div, 3*div + div//2],
            [0, div + div//2, 2*div, 2*div + div//2, 3*div],
            [0, div//2, 2*div, 3*div],
            [0, div, div + div//2, 2*div + div//2, 3*div + div//2],
        ]
        for bs in range(2 * bar, song_end, bar):
            if rng_bass.random() > mix_float(0.12, 0.96, rewrite):
                continue
            root = active_root_for_tick(bs, roots)
            pattern = bass_patterns[(rng_bass.randrange(len(bass_patterns)) + (bs // bar) + variant) % len(bass_patterns)]
            for pi, off in enumerate(pattern):
                if bs + off >= song_end:
                    continue
                pc = root if (pi % 4 != 2 or rng_bass.random() > 0.35 * rewrite) else chord_tones_for_root(root, scale)[1]
                p = nearest_pitch(pc, bass_center + rng_bass.choice([-12, 0, 0, 0]))
                dur = div//2 if off % div else int(div * mix_float(0.60, 0.82, rewrite))
                add_mel(bass, 1, pitch_into_range(p, bass_lo, bass_hi), bs + off, min(dur, song_end-(bs+off)), 62 + int(46 * rewrite) - pi*2, "bass", bass_lo, bass_hi, rng_bass)
    bass.append(make_meta(song_end, 0x2F, b"", order=99)); new_tracks.append(bass)

    # -----------------------------
    # Arp / pluck.
    # -----------------------------
    arp_src = notes_for_role(analysis, "arp") or all_notes
    pluck = setup_track(f"{style_name.upper()} PLUCK / ARP", ch=2, program=resolved_program(style_preset, "pluck", 5, use_style_instruments=use_style_instruments), volume=role_volume("pluck", 64 + brightness * 30 + rewrite * 8), pan=82, reverb=int(18 + reverb_amount * 48), chorus=int(12 + brightness * 30))
    skip_mod = max(2, int(round(15 - 10 * arp_density - 4 * rewrite)))
    for i, n in enumerate(arp_src):
        if n.start >= song_end:
            continue
        if rng_arp.random() > (0.95 if intensity < 0.08 else max(0.04, (1.0 - 0.72 * rewrite) * accomp_gate)):
            continue
        if skip_mod > 2 and (i + pluck_phase) % skip_mod == skip_mod - 1 and n.start > 16*bar:
            continue
        st = quantize_tick(n.start, div // (8 if intensity < 0.22 else 4))
        dur = max(div // 10, int(n.duration * mix_float(0.55, 0.34, rewrite)))
        p = pitch_into_range(n.pitch - (12 if n.pitch > arp_hi else 0), arp_lo, arp_hi)
        if harmony_lock:
            p = maybe_mutate_pitch(p, st, arp_lo, arp_hi, roots, scale, rng_arp, rewrite * 0.85, chord_bias=max(0.42, harmony_strictness * 0.72))
        add_mel(pluck, 2, p, st, min(dur, song_end-st), n.vel * mix_float(0.54, 0.34, rewrite), "pluck", arp_lo, arp_hi, rng_arp)
    if rewrite > 0.18:
        if accomp_relaxation > 0.78:
            steps = 4
        elif accomp_relaxation > 0.48:
            steps = 8
        else:
            steps = 8 if arp_density < 0.70 else 16
        step = div // (4 if steps == 16 else (2 if steps == 8 else 1))
        degree_templates = [[0,2,4,2], [0,4,2,6], [0,2,5,4], [2,4,6,4], [0,1,2,4]]
        for bs in range(4 * bar, song_end, bar):
            # Higher relaxation creates real breathing gaps instead of endless arpeggio chatter.
            if accomp_relaxation > 0.55 and ((bs // bar + variant4) % (3 if accomp_relaxation < 0.82 else 2) == 0):
                continue
            if rng_arp.random() > mix_float(0.10, 0.88, rewrite) * accomp_gate:
                continue
            root = active_root_for_tick(bs, roots)
            tmpl = rng_arp.choice(degree_templates)
            for s in range(steps):
                if rng_arp.random() < (0.18 * (1.0 - arp_density) + 0.46 * accomp_relaxation):
                    continue
                off = s * step + (hat_swing if (s % 2 and steps == 8) else 0)
                deg = tmpl[(s + variant + bs // bar) % len(tmpl)]
                p = choose_from_scale_degree(root, scale, deg, (arp_lo + arp_hi)//2 + rng_arp.choice([-12, 0, 0, 12]))
                add_mel(pluck, 2, pitch_into_range(p, arp_lo, arp_hi), bs + off, min(max(24, int(step * 0.58)), song_end-(bs+off)), 40 + int(44 * rewrite) + (s % 3)*4, "pluck", arp_lo, arp_hi, rng_arp)
    pluck.append(make_meta(song_end, 0x2F, b"", order=99)); new_tracks.append(pluck)

    # -----------------------------
    # Glass support copied from source, progressively replaced by seed-safe accents.
    # -----------------------------
    vibe_src = all_notes if len(all_notes) < 200 else sorted(all_notes, key=lambda n: (n.start, n.pitch))[vibe_offset::2]
    vibe = setup_track(f"{style_name.upper()} GLASS SUPPORT", ch=3, program=resolved_program(style_preset, "vibe", 11, use_style_instruments=use_style_instruments), volume=role_volume("vibe", 46 + brightness * 34), pan=36, reverb=int(24 + reverb_amount * 58), chorus=int(16 + brightness * 34))
    for i, n in enumerate(vibe_src):
        if n.start >= song_end or i % 5 == 4:
            continue
        if rng_lead.random() > max(0.03, (0.72 - 0.50 * rewrite) * accomp_gate):
            continue
        st = quantize_tick(n.start + (div//2 if i % 8 == 3 and rewrite > 0.25 else 0), div // 4)
        if st >= song_end:
            continue
        p = pitch_into_range(n.pitch + (12 if n.pitch < lead_lo else 0), max(52, lead_lo), lead_hi)
        if harmony_lock:
            p = maybe_mutate_pitch(p, st, max(52, lead_lo), lead_hi, roots, scale, rng_lead, rewrite * 0.72, chord_bias=max(0.58, harmony_strictness * 0.78))
        add_mel(vibe, 3, p, st, min(max(36, int(n.duration * mix_float(0.42, 0.28, rewrite))), song_end-st), n.vel * mix_float(0.34, 0.24, rewrite), "vibe", max(52, lead_lo), lead_hi, rng_lead)
    if rewrite > 0.42:
        for bs in range(8 * bar, song_end, 2 * bar):
            if accomp_relaxation > 0.58 and ((bs // bar + variant) % 4 == 0):
                continue
            if rng_lead.random() > rewrite * accomp_gate:
                continue
            root = active_root_for_tick(bs, roots)
            for k, deg in enumerate(rng_lead.choice([[4,2,0], [2,4,5], [6,4,2], [5,4,2]])):
                p = choose_from_scale_degree(root, scale, deg, lead_center + rng_lead.choice([-12, 0, 0]))
                add_mel(vibe, 3, pitch_into_range(p, max(52, lead_lo), lead_hi), bs + k * div, min(div//2, song_end-(bs+k*div)), 38 + int(36 * rewrite) - k*3, "vibe", max(52, lead_lo), lead_hi, rng_lead)
    vibe.append(make_meta(song_end, 0x2F, b"", order=99)); new_tracks.append(vibe)

    # Soft tonal ticks from dense sources; at high intensity seed changes the pattern heavily.
    ticks = setup_track(f"{style_name.upper()} TONAL TICKS", ch=4, program=resolved_program(style_preset, "ticks", 115, use_style_instruments=use_style_instruments), volume=role_volume("ticks", 28 + brightness * 26 + rewrite * 14), pan=96, reverb=int(8 + reverb_amount * 42), chorus=int(4 + brightness * 18))
    tick_src = notes_for_role(analysis, "hook_problem") or notes_for_role(analysis, "arp") or all_notes
    max_ticks = int(mix_float(80, 1400, max(arp_density, rewrite)) * mix_float(1.0, 0.12, accomp_relaxation))
    for i, n in enumerate(tick_src[:max_ticks]):
        if n.start >= song_end or i % 3 == 2:
            continue
        if accomp_relaxation > 0.50 and ((n.start // bar + variant4) % (3 if accomp_relaxation < 0.82 else 2) == 0):
            continue
        if rng_arp.random() > mix_float(0.32, 0.86, rewrite) * pulse_gate:
            continue
        st = quantize_tick(n.start + rng_arp.choice([0, 0, div//8, -div//8]) * (1 if rewrite > 0.55 else 0), div // 8)
        if harmony_lock:
            tick_chord = chord_tones_for_root(active_root_for_tick(st, roots), scale, seventh=True)
            pc = tick_chord[((i // 4) + tick_phase + rng_arp.randrange(3 if rewrite > 0.5 else 1)) % len(tick_chord)]
            p = nearest_pitch(pc, 76 + rng_arp.choice([-12, 0, 12]))
        else:
            p = 74 + ((i // 4 + tick_phase) % 7)
        add_mel(ticks, 4, pitch_into_range(p, 56, 88), st, min(max(18, div//7), song_end-st), 32 + int(32 * rewrite) + (i % 4) * 5, "ticks", 56, 88, rng_arp)
    ticks.append(make_meta(song_end, 0x2F, b"", order=99)); new_tracks.append(ticks)

    # Pads: more original harmonic source at low intensity, seed-derived voicing/progression at high intensity.
    pad = setup_track(f"{style_name.upper()} PAD", ch=5, program=resolved_program(style_preset, "pad", 89, use_style_instruments=True), volume=role_volume("pad", 42 + pad_density * 30 + rewrite * 6 + accomp_relaxation * 16), pan=62, reverb=int(36 + reverb_amount * 64), chorus=int(28 + brightness * 48))
    for idx, (st, root) in enumerate(roots):
        if st < 2 * bar or st >= song_end:
            continue
        if pad_density < 0.45 and idx % 3 == 1 and accomp_relaxation < 0.65:
            continue
        if rng_pad.random() > mix_float(0.78, 0.98, rewrite):
            continue
        seventh = (rng_pad.random() < mix_float(0.10, 0.56, rewrite)) and len(scale) >= 6
        pcs = chord_tones_for_root(root, scale, seventh=seventh)
        if rewrite > 0.70 and rng_pad.random() < 0.4:
            pcs = pcs[1:] + pcs[:1]  # inversion
        dur = min(int(mix_float(bar * 2 - div // 4, bar * rng_pad.choice([1,2,2,4]), rewrite) * mix_float(1.0, 1.65, accomp_relaxation)), song_end - st)
        for j, pc in enumerate(pcs):
            p = nearest_pitch(pc, pad_center + j * rng_pad.choice([4,5,7]) + (variant4 - 1) * 2)
            if j == 0 and p > 55:
                p -= 12
            add_note(pad, 5, p, st + j * 4, max(div//2, dur - j*4), 36 + j*6 + int(12 * rewrite))
    pad.append(make_meta(song_end, 0x2F, b"", order=99)); new_tracks.append(pad)

    # v0.2.7: accompaniment relaxation replacement layer.
    # When the slider is moved right, fast accompaniment pulses are thinned out
    # and these long style-safe string/pad swells create deliberate rest phases.
    if accomp_relaxation > 0.18:
        relief = setup_track(
            f"{style_name.upper()} RELIEF STRINGS", ch=0,
            program=resolved_program(style_preset, "strings", 48, use_style_instruments=True),
            volume=role_volume("relief", 22 + accomp_relaxation * 46 + pad_density * 10),
            pan=70, reverb=int(52 + reverb_amount * 70), chorus=int(26 + brightness * 38),
        )
        relief_every = 4 * bar if accomp_relaxation < 0.66 else 2 * bar
        relief_start = 8 * bar
        for ridx, bs in enumerate(range(relief_start, song_end, relief_every)):
            if bs >= song_end:
                break
            # Leave some holes so it breathes rather than becoming a wall of strings.
            if accomp_relaxation < 0.72 and (ridx + variant4) % 3 == 1:
                continue
            root = active_root_for_tick(bs, roots)
            pcs = chord_tones_for_root(root, scale, seventh=(rng_relief.random() < 0.30 + 0.30 * rewrite))
            dur = min(int(relief_every * mix_float(0.72, 1.65, accomp_relaxation)), song_end - bs)
            for j, pc in enumerate(pcs[:4]):
                center = pad_center + j * 5 + rng_relief.choice([-7, 0, 0, 7])
                p = nearest_pitch(pc, center)
                if j == 0 and p > 56:
                    p -= 12
                add_note(relief, 0, pitch_into_range(p, 40, 76), bs + j * 8, max(div, dur - j * 8), 26 + int(28 * accomp_relaxation) + j * 4)
        relief.append(make_meta(song_end, 0x2F, b"", order=99)); new_tracks.append(relief)

    # Icon hook: source-derived at low/mid intensity, seed-composed motif at high intensity.
    hook_src = notes_for_role(analysis, "hook_problem") or notes_for_role(analysis, "lead") or all_notes
    motif_notes = sorted(hook_src, key=lambda n: (n.start, -n.pitch))[:24]
    motif: list[int] = []
    if not motif_notes:
        motif = [nearest_pitch(tonic, hook_lo + 12), nearest_pitch(scale[2], hook_lo + 12), nearest_pitch(scale[4], hook_lo + 12), nearest_pitch(scale[3], hook_lo + 12)]
    else:
        sampled = motif_notes[:min(12, len(motif_notes))]
        for n in sampled:
            p = pitch_into_range(n.pitch, hook_lo, hook_hi)
            if harmony_lock:
                p = sanitize_copied_pitch(p, hook_lo, hook_hi, n.start, roots, scale, chord_bias=max(0.82, harmony_strictness))
            motif.append(p)
        compact: list[int] = []
        for p in motif:
            if not compact or compact[-1] != p:
                compact.append(p)
        motif = (compact or motif)[:8]
    if rewrite > 0.42 or len(motif) < 4:
        root = active_root_for_tick(16 * bar if song_end > 32 * bar else 4 * bar, roots)
        templates = [[0,2,4,5,4,2], [4,3,2,0,2,4], [0,4,5,4,2,1], [2,4,6,5,4,2], [0,1,3,4,3,1], [5,4,2,0,2,3]]
        tmpl = rng_hook.choice(templates)
        generated = [pitch_into_range(choose_from_scale_degree(root, scale, deg, lead_center + rng_hook.choice([-12, 0, 0, 12])), hook_lo, hook_hi) for deg in tmpl]
        if motif and rewrite < 0.88:
            # Blend source and generated motif. The slider decides how much survives from source.
            blended = []
            for i in range(max(len(motif), len(generated))):
                if i < len(motif) and rng_hook.random() > rewrite:
                    blended.append(motif[i])
                else:
                    blended.append(generated[i % len(generated)])
            motif = blended[:6]
        else:
            motif = generated[:6]
    if motif:
        rot = rng_hook.randrange(len(motif)) if rewrite > 0.18 else (variant4 % len(motif))
        motif = motif[rot:] + motif[:rot]
        motif = [pitch_into_range(p + (hook_transpose if rng_hook.random() < rewrite else 0), hook_lo, hook_hi) for p in motif]

    hook = setup_track(f"{style_name.upper()} ICON HOOK", ch=6, program=resolved_program(style_preset, "hook", 80, use_style_instruments=use_style_instruments), volume=role_volume("hook", 62 + brightness * 28 + rewrite * 10), pan=28, reverb=int(20 + reverb_amount * 52), chorus=int(18 + brightness * 42))
    section_step = 8 * bar
    start_section = 16 * bar if song_end > 32 * bar else 4 * bar
    rhythm_patterns = [
        [0, div, div + div//2, 2*div + div//2, 3*div, 3*div + div//2],
        [0, div//2, div + div//2, 2*div, 2*div + div//2, 3*div + div//2],
        [0, div, div*2, div*2 + div//2, 3*div, 3*div + div//2],
        [0, div//2, div, div + div//2, 2*div + div//2, 3*div],
        [0, div//2, div + div//2, 2*div + div//2, 3*div, 3*div + div//4],
        [0, div, div + div//2, 2*div, 3*div, 3*div + div//2],
    ]
    dur_patterns = [
        [div*3//4, div//3, div//3, div*2//3, div//2, div//3],
        [div//2, div//2, div//3, div//2, div//3, div*2//3],
        [div*3//4, div*3//4, div//2, div//3, div//2, div//3],
        [div//3, div//2, div//2, div//3, div*2//3, div//2],
        [div//2, div//3, div//2, div//3, div//2, div//2],
        [div, div//3, div//2, div//2, div//3, div//2],
    ]
    for sec_start in range(start_section, song_end, section_step):
        base_reps = 1 if intensity < 0.42 else (2 if intensity < 0.82 else rng_hook.choice([2, 2, 3]))
        reps = max(1, int(round(base_reps * mix_float(1.0, 0.45, accomp_relaxation))))
        for rep in range(reps):
            phrase = sec_start + rep * 2 * bar
            if phrase >= song_end:
                continue
            pat_idx = rng_hook.randrange(len(rhythm_patterns)) if rewrite > 0.28 else variant4
            for k, p in enumerate(motif[:6]):
                rhythm = rhythm_patterns[pat_idx][k % 6]
                dur = dur_patterns[pat_idx][k % 6]
                p2 = p + (12 if k == 0 and sec_start >= song_end * 0.65 and rng_hook.random() < 0.65 else 0)
                if harmony_lock and rng_hook.random() < rewrite:
                    p2 = maybe_mutate_pitch(p2, phrase + rhythm, hook_lo, hook_hi, roots, scale, rng_hook, rewrite * 0.45, chord_bias=0.85)
                add_mel(hook, 6, pitch_into_range(p2, hook_lo, hook_hi), phrase + rhythm, min(dur, song_end-(phrase+rhythm)), 74 + int(16*rewrite) - k*3, "hook", hook_lo, hook_hi, rng_hook)
            answer = phrase + 3*div
            if answer < song_end and intensity > 0.18:
                for k, p in enumerate(reversed(motif[:3])):
                    add_mel(hook, 6, pitch_into_range(p-12, max(40, hook_lo-12), max(52, hook_hi-10)), answer + k*(div//2), min(div//3, song_end-(answer+k*(div//2))), 48 + int(10*rewrite)-k*4, "hook_answer", max(40, hook_lo-12), max(52, hook_hi-10), rng_hook)
    hook.append(make_meta(song_end, 0x2F, b"", order=99)); new_tracks.append(hook)

    # Lead contour.
    lead_src = notes_for_role(analysis, "lead") or hook_src
    lead = setup_track(f"{style_name.upper()} LEAD CONTOUR", ch=7, program=resolved_program(style_preset, "lead", 81, use_style_instruments=use_style_instruments), volume=role_volume("lead", 50 + brightness * 32 + rewrite * 8), pan=104, reverb=int(20 + reverb_amount * 50), chorus=int(16 + brightness * 38))
    last_st_pitch: tuple[int, int] | None = None
    for i, n in enumerate(lead_src):
        if n.start >= song_end:
            continue
        if rng_lead.random() > max(0.05, 0.92 - 0.82 * rewrite):
            continue
        st = quantize_tick(n.start, div // 4)
        p = pitch_into_range(n.pitch, lead_lo, lead_hi)
        if harmony_lock:
            p = maybe_mutate_pitch(p, st, lead_lo, lead_hi, roots, scale, rng_lead, rewrite * 0.90, chord_bias=max(0.50, harmony_strictness * 0.70))
        if last_st_pitch == (st, p) and i % 2:
            continue
        if intensity > 0.70 and (i + variant) % max(7, int(35 - 22 * rewrite)) == 0 and n.start > 24 * bar:
            continue
        last_st_pitch = (st, p)
        dur = max(div//8, int(n.duration * mix_float(0.72, 0.42, rewrite)))
        add_mel(lead, 7, p, st, min(dur, song_end-st), n.vel * mix_float(0.50, 0.34, rewrite), "lead", lead_lo, lead_hi, rng_lead)
    if rewrite > 0.62:
        templates = [[0,2,4,2], [4,5,4,2], [2,0,2,4], [6,5,4,2], [1,3,4,6]]
        for bs in range(24 * bar, song_end, 8 * bar):
            root = active_root_for_tick(bs, roots)
            tmpl = rng_lead.choice(templates)
            for k, deg in enumerate(tmpl):
                st = bs + k * div + rng_lead.choice([0, div//2])
                if st >= song_end:
                    continue
                p = choose_from_scale_degree(root, scale, deg, lead_center + rng_lead.choice([-12, 0, 0, 12]))
                add_mel(lead, 7, pitch_into_range(p, lead_lo, lead_hi), st, min(div//2, song_end-st), 50 + int(32 * rewrite)-k*3, "lead", lead_lo, lead_hi, rng_lead)
    lead.append(make_meta(song_end, 0x2F, b"", order=99)); new_tracks.append(lead)

    # Support echo.
    echo_src = all_notes[::max(1, len(all_notes)//1000)] if len(all_notes) > 1000 else all_notes
    echo = setup_track(f"{style_name.upper()} SUPPORT ECHO", ch=8, program=resolved_program(style_preset, "echo", 88, use_style_instruments=use_style_instruments), volume=role_volume("echo", (20 + brightness * 18 + delay_amount * 24 + rewrite * 10) * mix_float(1.0, 0.65, accomp_relaxation)), pan=72, reverb=int(22 + reverb_amount * 56), chorus=int(18 + brightness * 42))
    for i, n in enumerate(echo_src):
        if n.start >= song_end or i % 7 == 6:
            continue
        if accomp_relaxation > 0.52 and ((n.start // bar + variant4) % (3 if accomp_relaxation < 0.82 else 2) == 0):
            continue
        if rng_echo.random() > mix_float(0.18, 0.72, rewrite) * mix_float(1.0, 0.30, accomp_relaxation):
            continue
        st = quantize_tick(n.start + (div//2 if (i + variant) % 8 == 3 else 0), div // 4)
        p = pitch_into_range(n.pitch, max(44, lead_lo-8), lead_hi)
        if harmony_lock:
            p = maybe_mutate_pitch(p, st, max(44, lead_lo-8), lead_hi, roots, scale, rng_echo, rewrite * 0.85, chord_bias=max(0.46, harmony_strictness * 0.68))
        dur = max(div//6, int(n.duration * mix_float(0.72, 0.48, rewrite) * mix_float(1.0, 1.45, accomp_relaxation)))
        add_mel(echo, 8, p, st, min(dur, song_end-st), n.vel * mix_float(0.22, 0.32, rewrite), "echo", max(44, lead_lo-8), lead_hi, rng_echo)
    echo.append(make_meta(song_end, 0x2F, b"", order=99)); new_tracks.append(echo)

    # Drums: seed-dependent variations and fills grow with intensity.
    drums = setup_track(f"{style_name.upper()} DRUMS - {drum_feel}", ch=9, program=None, volume=role_volume("drums", 100 + distortion * 22), pan=64, reverb=int(8 + reverb_amount * 28), chorus=4)
    start_drum = 2 * bar
    if drum_feel in ("no_drums", "none", "no_percussion", "silent"):
        # Explicit no-drums style. Keep an empty track for compatibility, but
        # do not add audible percussion events.
        drums.append(make_meta(song_end, 0x2F, b"", order=99))
        new_tracks.append(drums)
        reset = [make_meta(0, 0x03, b"RESET/SYSEX", order=0), make_meta(song_end, 0x2F, b"", order=99)]
        new_tracks.append(reset)
        out_mid.parent.mkdir(parents=True, exist_ok=True)
        write_midi(out_mid, 1, div, new_tracks)
        log(progress, f"MIDI geschrieben: {out_mid}")
        return out_mid, analysis
    for bs in range(start_drum, song_end, bar):
        bar_i = bs // bar
        bar_rng = seeded_rng(seed, f"drums:{bar_i}:{drum_feel}")

        if drum_feel in ("ambient",):
            if bar_i % 4 == 0:
                add_note(drums, 9, 49, bs, div, 30 + int(20 * rewrite))
            if bar_i % 2 == 1 or bar_rng.random() < 0.20 * rewrite:
                add_note(drums, 9, 42, bs + 2*div + hat_swing, 70, 24 + int(16 * rewrite))
            continue

        if drum_feel in ("rock", "metal", "punk", "pop"):
            # Backbeat family for rock/pop/punk/metal-inspired styles.
            kick_patterns = {
                "pop": [[0, 2*div + div//2], [0, div + div//2, 2*div + div//2]],
                "rock": [[0, div + div//2, 2*div + div//2], [0, 2*div, 3*div]],
                "punk": [[0, div, 2*div, 3*div], [0, div//2, div, 2*div, 3*div]],
                "metal": [[0, div//2, div, 2*div, 2*div + div//2, 3*div], [0, div//2, div, div + div//2, 2*div, 3*div]],
            }
            choices = kick_patterns.get(drum_feel, kick_patterns["rock"])
            kicks = choices[0] if rewrite < 0.30 else bar_rng.choice(choices)
            for off in kicks:
                add_note(drums, 9, 36, bs + off, 44, 92 + int(26 * rewrite))
            for off in [div, 3*div]:
                add_note(drums, 9, 38, bs + off, 55, 104 + int(12 * rewrite))
            hat_step = div//4 if drum_feel in ("punk", "metal") else div//2
            steps = 16 if hat_step == div//4 else 8
            for h in range(steps):
                if drum_feel == "metal" and h % 4 == 0:
                    add_note(drums, 9, 49, bs + h*hat_step, 28, 46 + int(18*rewrite))
                else:
                    add_note(drums, 9, 42 if h % 4 else 46, bs + h*hat_step, 22, 38 + int(22*rewrite) + (h % 2)*6)
            if bar_i % 4 == 3 or bar_rng.random() < 0.25 * rewrite:
                for k, note in enumerate(bar_rng.choice([[45,43,41], [47,45,43,41], [50,47,45]])):
                    add_note(drums, 9, note, bs + 3*div + k*(div//5), 48, 76-k*5)
            continue

        if drum_feel in ("moombahton", "reggaeton"):
            # Dembow/moombahton family. Slightly syncopated, useful for 100-115 BPM styles.
            for off in [0, 2*div + div//2]:
                add_note(drums, 9, 36, bs + off, 44, 92 + int(18*rewrite))
            for off in [div, 2*div, 3*div]:
                add_note(drums, 9, 38, bs + off, 52, 88 + int(14*rewrite))
            for h in range(8):
                swing = hat_swing if h % 2 else 0
                note = 42 if h % 2 else 46
                add_note(drums, 9, note, bs + h*(div//2) + swing, 22, 42 + int(18*rewrite) + (h % 3)*4)
            if bar_i % 4 == 3 or bar_rng.random() < 0.30 * rewrite:
                for k, note in enumerate(bar_rng.choice([[37, 38, 37], [75, 75, 38], [45, 43, 41]])):
                    add_note(drums, 9, note, bs + 3*div + k*(div//6), 36, 58-k*4)
            continue

        if drum_feel in ("ska", "reggae", "dub"):
            # One-drop/offbeat family.
            if drum_feel == "ska":
                add_note(drums, 9, 36, bs, 42, 82 + int(10*rewrite))
                add_note(drums, 9, 38, bs + 2*div, 50, 92 + int(10*rewrite))
                for beat in range(4):
                    add_note(drums, 9, 42, bs + beat*div + div//2 + hat_swing, 24, 48 + int(20*rewrite))
            else:
                add_note(drums, 9, 36, bs + 2*div, 50, 96 + int(12*rewrite))
                add_note(drums, 9, 38, bs + 2*div + 8, 55, 88 + int(8*rewrite))
                if drum_feel == "dub" and (bar_i % 4 == 3 or bar_rng.random() < 0.22*rewrite):
                    add_note(drums, 9, 38, bs + 3*div + div//2, 60, 58 + int(20*rewrite))
                for beat in range(4):
                    add_note(drums, 9, 42, bs + beat*div + div//2 + hat_swing, 28, 34 + int(15*rewrite))
            if bar_rng.random() < 0.35 * rewrite:
                add_note(drums, 9, 37, bs + 3*div + div//2, 32, 46 + int(16*rewrite))
            continue

        if drum_feel in ("folk", "bossa", "latin", "jazz"):
            if drum_feel == "jazz":
                # light ride pattern, bass drum feathering and snare accents
                for beat in range(4):
                    add_note(drums, 9, 51, bs + beat*div, 26, 54 + int(14*rewrite))
                    if beat in (1, 3):
                        add_note(drums, 9, 51, bs + beat*div + div//2 + hat_swing, 20, 38 + int(10*rewrite))
                add_note(drums, 9, 36, bs, 32, 48 + int(12*rewrite))
                add_note(drums, 9, 38, bs + 2*div, 38, 54 + int(16*rewrite))
            elif drum_feel == "bossa":
                for off in [0, 2*div + div//2]:
                    add_note(drums, 9, 36, bs + off, 34, 60 + int(16*rewrite))
                for off in [div, 2*div, 3*div]:
                    add_note(drums, 9, 37, bs + off + hat_swing, 26, 45 + int(14*rewrite))
                for h in range(8):
                    add_note(drums, 9, 42, bs + h*(div//2), 18, 32 + (h%2)*8)
            elif drum_feel == "latin":
                for off in [0, div + div//2, 2*div + div//2, 3*div]:
                    add_note(drums, 9, 36, bs + off, 35, 72 + int(18*rewrite))
                for off in [div, 3*div]:
                    add_note(drums, 9, 38, bs + off, 40, 70 + int(16*rewrite))
                for h in range(8):
                    add_note(drums, 9, 75 if h%3==0 else 42, bs + h*(div//2) + (hat_swing if h%2 else 0), 20, 42 + int(18*rewrite))
            else:  # folk
                add_note(drums, 9, 36, bs, 40, 70 + int(14*rewrite))
                add_note(drums, 9, 38, bs + 2*div, 45, 72 + int(14*rewrite))
                for h in range(4):
                    add_note(drums, 9, 42, bs + h*div + div//2, 22, 34 + int(10*rewrite))
            continue

        if drum_feel in ("orchestral", "classical"):
            # Sparse timpani/cymbal orchestral punctuation rather than a kit groove.
            root_pc = active_root_for_tick(bs, roots)
            timp = 47 if (root_pc % 2) else 45
            if bar_i % 2 == 0:
                add_note(drums, 9, timp, bs, div//2, 54 + int(22*rewrite))
            if bar_i % 4 == 3 or bar_rng.random() < 0.16 * rewrite:
                add_note(drums, 9, 49, bs + 3*div, div, 50 + int(22*rewrite))
            if bar_i % 8 == 7 and rewrite > 0.35:
                for k, note in enumerate([47, 45, 43, 41]):
                    add_note(drums, 9, note, bs + 3*div + k*(div//6), 48, 70-k*5)
            continue

        if drum_feel in ("dnb", "jungle"):
            base_kicks = [[0, div + div//2, 2*div + div//2], [0, div//2, div + div//2, 3*div], [0, div + div//4, 2*div + div//2, 3*div + div//2]]
            for off in base_kicks[bar_rng.randrange(len(base_kicks)) if rewrite > 0.35 else 0]:
                add_note(drums, 9, 36, bs + off, 40, 88 + int(24 * rewrite))
            for off in [div, 3*div]:
                add_note(drums, 9, 38, bs + off, 50, 102 + int(12 * rewrite))
                add_note(drums, 9, 39, bs + off + 12, 42, 54)
            for s16 in range(16):
                if bar_rng.random() < 0.08 * rewrite:
                    continue
                swing = hat_swing if s16 % 2 else 0
                add_note(drums, 9, 42 if s16 % 4 else 44, bs + s16*(div//4) + swing, 22, 38 + (18 if s16 % 4 == 0 else 0) + bar_rng.randrange(0, int(12*rewrite)+1))
            if bar_i % 4 == 3 or bar_rng.random() < 0.22 * rewrite:
                fill_notes = bar_rng.choice([[47,45,43,41,43,45], [41,43,45,47], [50,48,47,45]])
                for k, note in enumerate(fill_notes):
                    add_note(drums, 9, note, bs + 3*div + k*(div//8), 40, 68-k*3)
            continue

        if drum_feel in ("halftime", "trap"):
            kicks = [(0, 112), (div//2, 74 + int(16*rewrite)), (2*div + div//2, 90 + int(10*rewrite))]
            if bar_rng.random() < 0.36 * rewrite:
                kicks.append((3*div + div//2, 72))
            for off, vel in kicks:
                add_note(drums, 9, 36, bs + off, 46, vel)
            add_note(drums, 9, 38, bs + 2*div, 58, 108 + int(10*rewrite))
            hat_steps = 16 if drum_feel == "trap" else 8
            for h in range(hat_steps):
                step = div // (4 if hat_steps == 16 else 2)
                swing = hat_swing if h % 2 else 0
                add_note(drums, 9, 42, bs + h*step + swing, 20, 38 + (h % 3) * 6 + bar_rng.randrange(0, int(18*rewrite)+1))
            if bar_i % 4 == 3 or bar_rng.random() < 0.28 * rewrite:
                for k in range(bar_rng.choice([4, 6, 8])):
                    add_note(drums, 9, 42, bs + 3*div + k*(div//12), 16, 44 + k*3)
            continue

        if drum_feel in ("breakbeat", "garage", "electro", "idm", "glitch", "trip_hop", "hip_hop", "funk"):
            kick_options = [[0, div + div//2, 3*div], [0, div//2, 2*div + div//2], [0, 2*div + div//2]]
            kicks = kick_options[0] if rewrite < 0.35 else bar_rng.choice(kick_options)
            if drum_feel == "trip_hop" and rewrite < 0.60:
                kicks = [0, 2*div + div//2]
            if drum_feel == "hip_hop":
                kicks = [0, div + div//2, 2*div + div//2] if rewrite < 0.55 else bar_rng.choice([[0, div + div//2, 2*div + div//2], [0, div//2, 2*div, 3*div + div//2]])
            if drum_feel == "funk":
                kicks = [0, div//2, div + div//2, 2*div + div//2, 3*div]
            for off in kicks:
                add_note(drums, 9, 36, bs + off, 44, 92 + int(12 * rewrite))
            snare_pos = 2*div if drum_feel in ("trip_hop", "hip_hop") else div
            add_note(drums, 9, 38, bs + snare_pos, 55, 100 + int(12 * rewrite))
            add_note(drums, 9, 38, bs + 3*div, 50, 72 + int(22 * rewrite))
            if drum_feel == "funk":
                add_note(drums, 9, 37, bs + div + div//2, 34, 48 + int(16 * rewrite))
            for h in range(8):
                if drum_feel in ("idm", "glitch") and (h + bar_i + fill_variant) % max(2, int(5 - 2*rewrite)) == 0:
                    add_note(drums, 9, 75, bs + h*(div//2) + bar_rng.randrange(0, max(1, div//12)), 18, 30 + int(22*rewrite))
                swing = hat_swing if h % 2 else 0
                add_note(drums, 9, 42, bs + h*(div//2) + swing, 24, 38 + (h % 2)*16 + bar_rng.randrange(0, int(12*rewrite)+1))
            continue

        # Four-on-the-floor family: synthwave, house, techno, trance, hardstyle, etc.
        for beat in range(4):
            kick = 36
            vel = 112 if beat == 0 else 96
            if drum_feel == "hardstyle":
                vel = 122
            add_note(drums, 9, kick, bs + beat * div, 42, vel + int(8 * rewrite))
        if drum_feel in ("techno", "acid", "psytrance", "trance", "house", "house_soft"):
            for beat in range(4):
                add_note(drums, 9, 46, bs + beat*div + div//2 + hat_swing, 34, 48 + int(brightness * 28) + bar_rng.randrange(0, int(10*rewrite)+1))
        if (bar_i % 4 in (1, 3) and intensity > 0.4) or bar_rng.random() < 0.20 * rewrite:
            if drum_feel not in ("house_soft",):
                add_note(drums, 9, 36, bs + 3*div + div//2, 36, 64 + int(20 * rewrite))
        for beat in (1, 3):
            add_note(drums, 9, 38, bs + beat*div, 50, 96 + int(12 * rewrite))
            if drum_feel not in ("techno", "acid"):
                add_note(drums, 9, 39, bs + beat*div + 10, 48, 50 + int(12 * rewrite))
        for e8 in range(8):
            if bar_rng.random() < 0.04 * rewrite:
                continue
            swing = hat_swing if e8 % 2 == 1 else 0
            note = 42 if drum_feel not in ("chiptune",) else 44
            vel = 42 + int(brightness*24) + ((10 + fill_variant) if e8 % 2 == 0 else 0) + bar_rng.randrange(0, int(14*rewrite)+1)
            add_note(drums, 9, note, bs + e8*(div//2) + swing, 28, vel)
        if intensity > 0.45 and drum_feel not in ("techno", "acid"):
            add_note(drums, 9, 46, bs + 2*div + div//2 + div//16, 55, 54 + int(12 * rewrite))
        if bar_i % 16 == 0:
            add_note(drums, 9, 49, bs, div, 60 + int(12 * rewrite))
        if bar_i % 8 == (7 - fill_variant % 2) or bar_rng.random() < 0.20 * rewrite:
            fill = bar_rng.choice([[47,45,43,41], [50,48,45], [45,43,41,43,45]])
            for k, note in enumerate(fill):
                add_note(drums, 9, note, bs + 3*div + k*(div//4), 52, 70-k*4)
    drums.append(make_meta(song_end, 0x2F, b"", order=99)); new_tracks.append(drums)

    reset = [make_meta(0, 0x03, b"RESET/SYSEX", order=0), make_meta(song_end, 0x2F, b"", order=99)]
    new_tracks.append(reset)

    out_mid.parent.mkdir(parents=True, exist_ok=True)
    write_midi(out_mid, 1, div, new_tracks)
    log(progress, f"MIDI geschrieben: {out_mid}")
    return out_mid, analysis

# -----------------------------
# Built-in WAV renderer
# -----------------------------
def midi_to_freq(note: int) -> float:
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def parse_tempo(mid: Path):
    fmt, ntr, div, tracks = parse_midi(mid)
    tempo = 500000
    for t in tracks:
        for e in t.events:
            if e.type == "meta" and e.meta_type == 0x51 and len(e.data) == 3:
                tempo = int.from_bytes(e.data, "big")
                return fmt, ntr, div, tracks, tempo
    return fmt, ntr, div, tracks, tempo


def collect_notes_for_render(mid: Path, progress: Progress | None = None):
    fmt, ntr, div, tracks, tempo = parse_tempo(mid)
    log(progress, f"[35%] Audio render: parsed {len(tracks)} track(s). Collecting notes...")
    end_tick = max([0] + [e.abs_tick for t in tracks for e in t.events])
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
                            "dur": max(0.025, (e.abs_tick - st) * sp_tick),
                            "pitch": e.data[0], "vel": vel, "ch": ch, "program": prog, "vol": vol, "pan": pan,
                            "track": ti,
                        })
    duration = end_tick * sp_tick + 2.0
    return notes, duration


def envelope(n: int, sr: int, attack=0.008, decay=0.05, sustain=0.7, release=0.04):
    import numpy as np
    if n <= 0:
        return np.zeros(0, dtype=np.float32)
    a = min(n, int(attack * sr))
    d = min(max(0, n-a), int(decay * sr))
    r = min(max(0, n-a-d), int(release * sr))
    s = max(0, n-a-d-r)
    parts = []
    if a:
        parts.append(np.linspace(0, 1, a, endpoint=False, dtype=np.float32))
    if d:
        parts.append(np.linspace(1, sustain, d, endpoint=False, dtype=np.float32))
    if s:
        parts.append(np.full(s, sustain, dtype=np.float32))
    if r:
        parts.append(np.linspace(sustain, 0, r, endpoint=True, dtype=np.float32))
    if not parts:
        return np.ones(n, dtype=np.float32)
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
    phase = 2*np.pi*f*t

    if ch == 9:
        if pitch == 36:
            n2 = max(1, int(0.42 * sr)); t2 = np.arange(n2, dtype=np.float32)/sr
            freq = 95*np.exp(-t2*22) + 38
            phase2 = 2*np.pi*np.cumsum(freq)/sr
            wave = np.sin(phase2) * np.exp(-t2*9.5)
            wave += 0.25*np.random.default_rng(1000+pitch+n2).normal(0,1,n2)*np.exp(-t2*45)
            return wave.astype(np.float32) * amp * 1.15
        if pitch in (38,39):
            n2 = max(1, int(0.34 * sr)); t2 = np.arange(n2, dtype=np.float32)/sr
            rng = np.random.default_rng(2000+pitch+n2)
            noise = rng.normal(0,1,n2)
            tone = np.sin(2*np.pi*185*t2) * np.exp(-t2*14)
            wave = (0.65*noise*np.exp(-t2*17) + 0.35*tone)
            if pitch == 39:
                wave *= (1 + 0.35*np.sin(2*np.pi*34*t2))
            return wave.astype(np.float32) * amp * 0.72
        if pitch in (42,46,49):
            n2 = max(1, int((0.08 if pitch==42 else 0.38 if pitch==46 else 1.1)*sr)); t2 = np.arange(n2, dtype=np.float32)/sr
            rng = np.random.default_rng(3000+pitch+n2)
            noise = rng.normal(0,1,n2)
            smooth = np.convolve(noise, np.ones(16)/16, mode='same')
            wave = (noise - smooth) * np.exp(-t2*(38 if pitch==42 else 7 if pitch==46 else 2.2))
            return wave.astype(np.float32) * amp * (0.23 if pitch==42 else 0.30)
        n2 = max(1, int(0.28*sr)); t2 = np.arange(n2, dtype=np.float32)/sr
        base = {47:190,45:155,43:125,41:95}.get(pitch, 160)
        wave = np.sin(2*np.pi*(base*np.exp(-t2*3.5))*t2) * np.exp(-t2*8)
        return wave.astype(np.float32) * amp * 0.58

    if ch == 1:
        wave = 0.58*np.tanh(2.2*np.sin(phase)) + 0.32*np.sin(phase*0.5)
        env = envelope(n, sr, attack=0.004, decay=0.04, sustain=0.62, release=0.035)
        wave *= env * 0.55
    elif ch == 2:
        wave = np.sin(phase + 1.8*np.sin(2*phase)*np.exp(-t*7.0)) + 0.22*np.sin(2*phase)
        env = envelope(n, sr, attack=0.003, decay=0.18, sustain=0.12, release=0.055)
        wave *= env * 0.34
    elif ch == 3:
        wave = np.sin(phase) + 0.35*np.sin(2.01*phase) + 0.18*np.sin(3.02*phase)
        env = envelope(n, sr, attack=0.006, decay=0.22, sustain=0.22, release=0.09)
        wave *= env * 0.24
    elif ch == 4:
        wave = np.sin(phase) + 0.22*np.sin(3*phase)
        env = envelope(n, sr, attack=0.001, decay=0.035, sustain=0.08, release=0.025)
        wave *= env * 0.13
    elif ch == 5:
        det = 0.006
        wave = 0.42*np.sin(phase) + 0.22*np.sin(2*np.pi*f*(1+det)*t) + 0.22*np.sin(2*np.pi*f*(1-det)*t)
        wave += 0.08*np.sin(2*phase)
        env = envelope(n, sr, attack=0.25, decay=0.22, sustain=0.82, release=0.35)
        wave *= env * 0.28
    elif ch == 6:
        vibr = 0.003*np.sin(2*np.pi*5.2*t)
        wave = 0.48*np.tanh(1.7*np.sin(phase*(1+vibr))) + 0.24*np.sin(phase) + 0.12*np.sin(2*phase)
        env = envelope(n, sr, attack=0.012, decay=0.08, sustain=0.72, release=0.075)
        wave *= env * 0.36
    elif ch == 7:
        wave = 0.35*np.tanh(2.0*np.sin(phase)) + 0.28*np.sin(phase) + 0.10*np.sin(2*phase)
        env = envelope(n, sr, attack=0.01, decay=0.08, sustain=0.56, release=0.07)
        wave *= env * 0.30
    elif ch == 8:
        frac = (f*t) % 1.0
        saw = 2*frac - 1
        wave = 0.22*saw + 0.30*np.sin(phase)
        env = envelope(n, sr, attack=0.01, decay=0.10, sustain=0.48, release=0.085)
        wave *= env * 0.21
    else:
        wave = np.sin(phase) * envelope(n, sr) * 0.2
    return (wave.astype(np.float32) * amp)


def render_wav(mid: Path | str, wav_path: Path | str, sr: int = 44100, progress: Progress | None = None):
    import numpy as np
    mid = Path(mid); wav_path = Path(wav_path)
    random.seed(20260527)
    np.random.seed(20260527)
    notes, duration = collect_notes_for_render(mid, progress=progress)
    total = int(duration * sr)
    mix = np.zeros((total, 2), dtype=np.float32)
    log(progress, f"[45%] Rendere WAV mit internem Synth: {len(notes)} Noten, ca. {duration:.1f}s")
    for idx, note in enumerate(notes):
        if progress and idx and idx % 250 == 0:
            pct = 45 + int((idx / max(1, len(notes))) * 40)
            log(progress, f"[{pct}%] Audio: {idx}/{len(notes)} Noten")
        audio = synth_note(note, sr)
        start = int(note["start"] * sr)
        end = min(total, start + len(audio))
        if end <= start:
            continue
        audio = audio[:end-start]
        pan = note["pan"] / 127.0
        left = math.cos(pan * math.pi/2)
        right = math.sin(pan * math.pi/2)
        mix[start:end, 0] += audio * left
        mix[start:end, 1] += audio * right
    for delay, amount in ((0.28, 0.16), (0.43, 0.08)):
        delay_s = int(delay * sr)
        if delay_s < total:
            mix[delay_s:] += mix[:-delay_s] * amount
    fade_len = min(total, int(2.0 * sr))
    if fade_len:
        fade = np.linspace(1.0, 0.0, fade_len, dtype=np.float32)
        mix[-fade_len:] *= fade[:, None]
    peak = float(np.max(np.abs(mix))) if total else 1.0
    if peak > 0:
        mix = mix / max(peak, 1.0) * 0.92
    mix = softclip(mix * 1.15) * 0.88
    out = np.int16(np.clip(mix, -1, 1) * 32767)
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(wav_path), "wb") as wf:
        wf.setnchannels(2)
        wf.setsampwidth(2)
        wf.setframerate(sr)
        wf.writeframes(out.tobytes())
    log(progress, f"[88%] WAV geschrieben: {wav_path}")
    return wav_path


def _is_real_ffmpeg(exe: str | Path) -> bool:
    try:
        proc = subprocess.run([str(exe), "-version"], text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=5)
        head = (proc.stdout or "").lower()[:300]
        return proc.returncode == 0 and "ffmpeg version" in head
    except Exception:
        return False


def find_usable_ffmpeg(base_dir: Path | None = None) -> str | None:
    candidates: list[str] = []
    env = os.environ.get("SYNTHWAVE_FFMPEG")
    if env:
        candidates.append(env)
    if base_dir:
        for rel in [
            "tools/ffmpeg/bin/ffmpeg.exe",
            "tools/ffmpeg/ffmpeg.exe",
            "portable_ffmpeg/ffmpeg.exe",
            "ffmpeg.exe",
        ]:
            candidates.append(str(base_dir / rel))
    found = shutil.which("ffmpeg")
    if found:
        candidates.append(found)
    # Avoid fake Python package shims named ffmpeg.exe by actively validating -version.
    seen = set()
    for c in candidates:
        if not c or c in seen:
            continue
        seen.add(c)
        if Path(c).exists() or shutil.which(c):
            if _is_real_ffmpeg(c):
                return c
    return None


def convert_mp3(wav_path: Path | str, mp3_path: Path | str, base_dir: Path | None = None, progress: Progress | None = None):
    wav_path = Path(wav_path); mp3_path = Path(mp3_path)
    ffmpeg = find_usable_ffmpeg(base_dir)
    if not ffmpeg:
        log(progress, "MP3 übersprungen: kein echtes ffmpeg gefunden. WAV ist trotzdem fertig.")
        return None
    cmd = [ffmpeg, "-y", "-i", str(wav_path), "-codec:a", "libmp3lame", "-b:a", "192k", str(mp3_path)]
    try:
        subprocess.run(cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        log(progress, f"MP3 geschrieben: {mp3_path}")
        return mp3_path
    except subprocess.CalledProcessError as exc:
        msg = (exc.stderr or exc.stdout or str(exc)).strip()
        log(progress, f"MP3-Konvertierung fehlgeschlagen, WAV bleibt nutzbar: {msg[:500]}")
        return None


def process_file(
    source: Path | str,
    output_dir: Path | str | None = None,
    prefix: str | None = None,
    render_audio: bool = True,
    render_mp3: bool = True,
    sample_rate: int = 44100,
    intensity: float = 0.65,
    target_bpm: float | None = None,
    repetition: float = 0.50,
    use_style_instruments: bool = False,
    preserve_source_volumes: bool = False,
    harmony_lock: bool = True,
    seed: int | None = None,
    style_id: str = "synthwave",
    random_style: bool = False,
    use_feedback: bool = False,
    feedback_path: Path | str | None = None,
    progress: Progress | None = None,
) -> dict:
    source = Path(source)
    seed = normalize_seed(seed)
    source_hash = source_midi_hash(source)
    feedback_profile = load_feedback_profile(feedback_path) if use_feedback else _empty_feedback_profile()
    style_preset = resolve_style_preset_with_feedback(style_id, random_style=random_style, seed=seed, profile=feedback_profile if use_feedback else None)
    resolved_style_id = str(style_preset.get("id", "synthwave"))
    resolved_style_name = str(style_preset.get("name", resolved_style_id))
    feedback_bias = {"enabled": False, "confidence": 0.0}
    effective_intensity = intensity
    effective_target_bpm = target_bpm
    effective_repetition = repetition
    effective_use_style_instruments = use_style_instruments
    effective_preserve_source_volumes = preserve_source_volumes
    effective_harmony_lock = harmony_lock
    if use_feedback:
        (
            style_preset,
            effective_intensity,
            effective_target_bpm,
            effective_repetition,
            effective_use_style_instruments,
            effective_preserve_source_volumes,
            effective_harmony_lock,
            feedback_bias,
        ) = apply_feedback_preferences(
            profile=feedback_profile,
            style_preset=style_preset,
            source_hash=source_hash,
            intensity=intensity,
            target_bpm=target_bpm,
            repetition=repetition,
            use_style_instruments=use_style_instruments,
            preserve_source_volumes=preserve_source_volumes,
            harmony_lock=harmony_lock,
            progress=progress,
        )
    else:
        log(progress, "Feedback learning: OFF")
    if output_dir is None:
        output_dir = source.parent / "reimagined_output"
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    if prefix is None or not str(prefix).strip():
        prefix = "{source}_{style}_seed{seed}"
    prefix = str(prefix)
    prefix = (
        prefix.replace("{source}", source.stem)
              .replace("{seed}", str(seed))
              .replace("{style}", safe_token(resolved_style_id))
              .replace("{style_name}", safe_token(resolved_style_name))
              .replace("{source_hash}", source_hash)
    )
    safe_prefix = "".join(ch if ch.isalnum() or ch in "-_. " else "_" for ch in prefix).strip() or f"{source.stem}_{resolved_style_id}_seed{seed}"
    mid = output_dir / f"{safe_prefix}.mid"
    wav = output_dir / f"{safe_prefix}.wav"
    mp3 = output_dir / f"{safe_prefix}.mp3"
    analysis_txt = output_dir / f"{safe_prefix}_analysis.txt"
    midi_path, analysis = build_reimagined_midi(
        source, mid, style=resolved_style_id, style_preset=style_preset,
        intensity=effective_intensity, target_bpm=effective_target_bpm, repetition=effective_repetition,
        use_style_instruments=effective_use_style_instruments, preserve_source_volumes=effective_preserve_source_volumes, harmony_lock=effective_harmony_lock, seed=seed, progress=progress,
    )
    tonic, mode, scale, key_confidence = detect_key_and_mode(analysis)
    generation_summary = (
        "Generation settings:\n"
        f"  Seed: {seed}\n"
        f"  Source MIDI hash: {source_hash}\n"
        f"  Style mode: {'random' if random_style else 'manual'}\n"
        f"  Requested style: {style_id}\n"
        f"  Resolved style: {resolved_style_id} ({resolved_style_name})\n"
        f"  Style preset version: {STYLE_PRESET_VERSION}\n"
        f"  Style instruments: {style_preset.get('instruments', '')}\n"
        f"  Style meter: {style_preset.get('meter', '')}\n"
        f"  Style drum feel: {style_preset.get('drum_feel', '')}\n"
        f"  Feedback learning: {'ON' if use_feedback else 'OFF'}\n"
        f"  Feedback influence: {float(feedback_bias.get('confidence', 0.0)):.2f} ({int(feedback_bias.get('profile_count', 0) or 0)} relevant rating(s), approval {float(feedback_bias.get('approval', 0.0) or 0.0):+.2f})\n"
        f"  Preserve source track volumes: {'ON' if effective_preserve_source_volumes else 'OFF'} (requested {'ON' if preserve_source_volumes else 'OFF'})\n"
        f"  Harmony lock: {'ON' if effective_harmony_lock else 'OFF'} (requested {'ON' if harmony_lock else 'OFF'})\n"
        f"  Detected key/mode: {NOTE_NAMES[tonic]} {mode} (confidence {key_confidence:.2f})\n"
        f"  Intensity: {intensity:.2f}\n"
        f"  Effective intensity: {effective_intensity:.2f}\n"
        f"  Rewrite amount: {smoothstep01(effective_intensity):.2f}\n"
        f"  Target BPM: {target_bpm if target_bpm is not None else 'auto'}\n"
        f"  Effective BPM: {effective_target_bpm if effective_target_bpm is not None else 'auto'}\n"
        f"  Accompaniment relaxation: {repetition:.2f} (0.00 = dense/active accompaniment, 1.00 = more breathing room, fewer rapid attacks, more pads)\n"
        f"  Effective accompaniment relaxation: {effective_repetition:.2f}\n"
        f"  Style lead/melody instruments: {'ON' if effective_use_style_instruments else 'OFF'} (requested {'ON' if use_style_instruments else 'OFF'})\n"
        f"  Slider behavior: intensity 0.00 = source-like cleanup, intensity 1.00 = mostly regenerated arrangement in resolved style\n"
        f"  Sample rate: {sample_rate}\n\n"
    )
    full_summary = generation_summary + analysis.summary
    analysis_txt.write_text(full_summary, encoding="utf-8")
    log(progress, f"Analyse gespeichert: {analysis_txt}")
    wav_path = None
    mp3_path = None
    if render_audio:
        wav_path = render_wav(midi_path, wav, sr=sample_rate, progress=progress)
        if render_mp3:
            mp3_path = convert_mp3(wav_path, mp3, base_dir=app_base_dir(), progress=progress)
    return {
        "midi": str(midi_path),
        "wav": str(wav_path) if wav_path else None,
        "mp3": str(mp3_path) if mp3_path else None,
        "analysis": str(analysis_txt),
        "seed": seed,
        "requested_style": style_id,
        "style": resolved_style_id,
        "style_name": resolved_style_name,
        "random_style": bool(random_style),
        "intensity": intensity,
        "effective_intensity": effective_intensity,
        "target_bpm": target_bpm,
        "effective_bpm": effective_target_bpm,
        "accompaniment_relaxation": repetition,
        "effective_accompaniment_relaxation": effective_repetition,
        "repetition": repetition,
        "use_style_instruments": bool(use_style_instruments),
        "effective_use_style_instruments": bool(effective_use_style_instruments),
        "harmony_lock": bool(harmony_lock),
        "effective_harmony_lock": bool(effective_harmony_lock),
        "use_feedback": bool(use_feedback),
        "feedback_influence": float(feedback_bias.get("confidence", 0.0) or 0.0),
        "feedback_profile_count": int(feedback_bias.get("profile_count", 0) or 0),
        "preserve_source_volumes": bool(effective_preserve_source_volumes),
        "requested_preserve_source_volumes": bool(preserve_source_volumes),
        "source_hash": source_hash,
        "summary": full_summary,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Analyze a MIDI, create a cleaner derivative electronic variation with selectable style presets, render WAV and optional MP3.")
    ap.add_argument("source", help="Input .mid/.midi file")
    ap.add_argument("--out-dir", default=None, help="Output directory")
    ap.add_argument("--prefix", default=None, help="Output filename prefix")
    ap.add_argument("--no-audio", action="store_true", help="Only write MIDI and analysis")
    ap.add_argument("--no-mp3", action="store_true", help="Skip MP3 conversion")
    ap.add_argument("--sample-rate", type=int, default=44100, help="WAV sample rate")
    ap.add_argument("--intensity", type=float, default=0.65, help="Transformation intensity 0.0-1.0")
    ap.add_argument("--bpm", type=float, default=None, help="Optional exact target BPM. Omit for source/style-derived auto BPM.")
    ap.add_argument("--repetition", type=float, default=0.50, help="Accompaniment relaxation 0.0-1.0. 0=dense/active pulses, 1=fewer rapid attacks and more pad/string relief.")
    ap.add_argument("--use-style-instruments", action="store_true", help="Use style preset GM programs for lead/melody tracks too.")
    ap.add_argument("--preserve-source-volumes", action="store_true", help="Keep generated role/track volumes close to the estimated loudness of the source tracks, even when instruments are replaced.")
    ap.add_argument("--no-harmony-lock", action="store_true", help="Disable scale/chord correction. Default keeps copied notes harmonically locked.")
    ap.add_argument("--seed", type=int, default=None, help="Reproducible generation seed. Omit for a new random seed each run.")
    ap.add_argument("--style", default="synthwave", help="Style preset id, e.g. synthwave, darksynth, techno, drum_and_bass. See app/styles/style_presets.json.")
    ap.add_argument("--random-style", action="store_true", help="Resolve a random style deterministically from the generation seed.")
    ap.add_argument("--use-feedback", action="store_true", help="Use local thumbs-up/thumbs-down feedback profile to gently bias future renders.")
    ap.add_argument("--feedback-path", default=None, help="Optional feedback profile JSON path. Default: app_data/feedback/ratings.json")
    args = ap.parse_args(argv)
    result = process_file(
        args.source,
        output_dir=args.out_dir,
        prefix=args.prefix,
        render_audio=not args.no_audio,
        render_mp3=not args.no_mp3,
        sample_rate=args.sample_rate,
        intensity=max(0.0, min(1.0, args.intensity)),
        target_bpm=args.bpm,
        repetition=max(0.0, min(1.0, args.repetition)),
        use_style_instruments=args.use_style_instruments,
        preserve_source_volumes=args.preserve_source_volumes,
        harmony_lock=not args.no_harmony_lock,
        seed=args.seed,
        style_id=args.style,
        random_style=args.random_style,
        use_feedback=args.use_feedback,
        feedback_path=args.feedback_path,
        progress=print,
    )
    print(json.dumps(result, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
