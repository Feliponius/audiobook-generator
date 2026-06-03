"""
TTS Caching, Rewrite Validation, and File Utilities
Ported from virgilash's fork contributions.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
import re
import subprocess
import wave
from pathlib import Path
from typing import List, Optional, Tuple


PRONUNCIATION_GLOSSARY_VERSION = 1


# ── File utilities ─────────────────────────────────────────────────


def wav_file_is_valid(path: Path) -> bool:
    if not path.exists() or path.stat().st_size <= 44:
        return False
    try:
        with wave.open(str(path), "rb") as wf:
            return wf.getnchannels() > 0 and wf.getframerate() > 0 and wf.getnframes() > 0
    except (wave.Error, EOFError, OSError):
        return False


def wav_sample_rate(path: Path) -> Optional[int]:
    try:
        with wave.open(str(path), "rb") as wf:
            return int(wf.getframerate())
    except (wave.Error, EOFError, OSError):
        return None


def file_fingerprint(path: Path) -> dict:
    try:
        st = path.stat()
        return {
            "path": str(path.expanduser().resolve()),
            "size": st.st_size,
            "mtime_ns": st.st_mtime_ns,
        }
    except OSError:
        return {"path": str(path.expanduser()), "missing": True}


def piper_config_sample_rate(config: Path) -> Optional[int]:
    data = _read_json_file(config, default={})
    if not isinstance(data, dict):
        return None
    candidates = [
        data.get("sample_rate"),
        data.get("sampleRate"),
        (data.get("audio") or {}).get("sample_rate") if isinstance(data.get("audio"), dict) else None,
    ]
    for candidate in candidates:
        try:
            if candidate:
                return int(candidate)
        except (TypeError, ValueError):
            continue
    return None


def encoded_output_is_current(input_path: Path, output_path: Path) -> bool:
    if not output_path.exists() or output_path.stat().st_size <= 0:
        return False
    try:
        return output_path.stat().st_mtime_ns >= input_path.stat().st_mtime_ns
    except OSError:
        return False


def _read_json_file(path: Path, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return default


# ── TTS Cache ──────────────────────────────────────────────────────


def tts_cache_path(wav_path: Path) -> Path:
    return wav_path.with_suffix(".tts-cache.json")


def build_tts_cache_payload(*, engine: str, tts_text: str, settings: dict) -> dict:
    return {
        "version": 1,
        "engine": engine,
        "tts_text_sha256": _sha256_text(tts_text),
        "pronunciation_glossary_version": PRONUNCIATION_GLOSSARY_VERSION,
        "settings": settings,
    }


def tts_cache_matches(wav_path: Path, payload: dict) -> bool:
    if not wav_file_is_valid(wav_path):
        return False
    cached = _read_json_file(tts_cache_path(wav_path), default=None)
    return cached == payload


def write_tts_cache(wav_path: Path, payload: dict) -> None:
    if wav_file_is_valid(wav_path):
        _write_json_atomic(tts_cache_path(wav_path), payload)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _write_json_atomic(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp.json")
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
        tmp.replace(path)
    except OSError:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


# ── HLS ADTS AAC ───────────────────────────────────────────────────


def write_hls_aac_segment_from_audio(audio: "np.ndarray", path: Path, sample_rate: int = 24000) -> None:
    """Write an audio segment as ADTS AAC for broad HLS compatibility."""
    import numpy as np
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 0:
        return
    wav_tmp = path.with_suffix(".tmp.wav")
    _write_wav_from_float32(wav_tmp, audio, sample_rate)
    cmd = [
        "ffmpeg", "-y", "-i", str(wav_tmp),
        "-c:a", "aac", "-b:a", "128k", "-f", "adts", str(path),
    ]
    run_quiet(cmd)
    wav_tmp.unlink(missing_ok=True)


def encode_wav_to_hls_aac(input_path: Path, output_path: Path, bitrate: str = "128k") -> None:
    """Encode a WAV file to an ADTS AAC HLS media segment."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if encoded_output_is_current(input_path, output_path):
        return
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c:a", "aac", "-b:a", bitrate, "-f", "adts",
        str(output_path),
    ]
    run_quiet(cmd)


def write_m3u8(playlist_path: Path, entries: List[Tuple[str, float]], *, endlist: bool = False) -> None:
    playlist_path.parent.mkdir(parents=True, exist_ok=True)
    target = max(1, max((math.ceil(duration) for _, duration in entries), default=1))
    with open(playlist_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write(f"#EXT-X-TARGETDURATION:{target}\n")
        f.write("#EXT-X-PLAYLIST-TYPE:EVENT\n")
        for name, dur in entries:
            f.write(f"#EXTINF:{dur:.3f},\n")
            f.write(f"{name}\n")
        if endlist:
            f.write("#EXT-X-ENDLIST\n")


def _write_wav_from_float32(path: Path, audio: "np.ndarray", sample_rate: int = 24000) -> None:
    import numpy as np
    audio_int16 = (audio * 32767).astype(np.int16)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())


def run_quiet(cmd: List[str]) -> None:
    try:
        subprocess.run(cmd, check=True, capture_output=True, text=True)
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip()
        stdout = (exc.stdout or "").strip()
        detail = stderr or stdout or "no output captured"
        raise RuntimeError(
            f"Command failed with exit code {exc.returncode}: {' '.join(cmd)}\n{detail}"
        ) from exc


# ── Rewrite validation ─────────────────────────────────────────────


def narration_word_count(text: str) -> int:
    return len(re.findall(r"\b\w+[\w'’-]*\b", text))


def dynamic_rewrite_max_tokens(text: str, *, cap: int = 1024) -> int:
    return min(cap, max(256, int(len(text) / 3) + 128))


def validate_rewrite_output(original: str, rewritten: str, *, finish_reason: Optional[str] = None) -> Tuple[bool, str]:
    """Reject rewrite outputs that look truncated or structurally unsafe."""
    try:
        from epub_to_audiobook import sanitize_narration_text
    except ImportError:
        def sanitize_narration_text(t): return t
    
    cleaned_original = sanitize_narration_text(original)
    cleaned_rewritten = sanitize_narration_text(rewritten)
    if not cleaned_rewritten:
        return False, "empty"
    if re.search(r"</?out>|</?text>", cleaned_rewritten, flags=re.I):
        return False, "tag_leak"
    if finish_reason and finish_reason.lower() in {"length", "max_tokens"}:
        return False, "truncated_by_token_limit"

    original_words = narration_word_count(cleaned_original)
    rewritten_words = narration_word_count(cleaned_rewritten)
    if original_words >= 40 and rewritten_words < max(12, int(original_words * 0.65)):
        return False, "too_short"
    if len(cleaned_original) >= 300 and len(cleaned_rewritten) < int(len(cleaned_original) * 0.45):
        return False, "too_short"
    return True, "ok"


def escape_ffmetadata_value(value: str) -> str:
    value = str(value).replace("\r\n", "\n").replace("\r", "\n")
    value = value.replace("\\", "\\\\")
    value = value.replace("\n", "\\n")
    for ch in ("=", ";", "#"):
        value = value.replace(ch, f"\\{ch}")
    return value


def split_oversized_unit(unit: str, max_chars: int) -> List[str]:
    import textwrap
    if len(unit) <= max_chars:
        return [unit]
    wrapped = textwrap.wrap(
        unit,
        width=max_chars,
        break_long_words=False,
        break_on_hyphens=False,
    )
    return [part.strip() for part in wrapped if part.strip()] or [unit]
