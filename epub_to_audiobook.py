#!/usr/bin/env python3
"""EPUB -> local audiobook pipeline using Piper TTS.

This script is designed to be resumable and low-touch:
- Extracts EPUB content with ebooklib + BeautifulSoup.
- Cleans and chunks text deterministically.
- Synthesizes each chunk with a local Piper voice.
- Concatenates chunk WAVs into chapter WAVs.
- Builds a final M4B with chapter markers.

Requirements (in a venv is fine):
  pip install piper-tts ebooklib beautifulsoup4 lxml

Example:
  python epub_to_audiobook.py input.epub \
    --voice-model ~/.local/share/piper/voices/en_US-lessac-medium/en_US-lessac-medium.onnx \
    --voice-config ~/.local/share/piper/voices/en_US-lessac-medium/en_US-lessac-medium.onnx.json \
    --outdir ./out
"""
from __future__ import annotations

import argparse
import dataclasses
import hashlib
import json
import multiprocessing as mp
import os
import re
import subprocess
import threading
import sys
import time
import urllib.error
import urllib.request
import textwrap
import wave
from datetime import datetime, timezone
from queue import Queue
from pathlib import Path
from typing import Iterable, List, Optional, Tuple

import numpy as np

from bs4 import BeautifulSoup
from ebooklib import epub, ITEM_DOCUMENT


DEFAULT_VOICE_MODEL = os.path.expanduser(
    "~/.local/share/piper/voices/en_US-lessac-medium/en_US-lessac-medium.onnx"
)
DEFAULT_VOICE_CONFIG = os.path.expanduser(
    "~/.local/share/piper/voices/en_US-lessac-medium/en_US-lessac-medium.onnx.json"
)


@dataclasses.dataclass
class Chapter:
    index: int
    title: str
    source: str
    text: str
    chunk_paths: List[Path] = dataclasses.field(default_factory=list)
    wav_path: Optional[Path] = None
    duration_s: Optional[float] = None


def log(msg: str) -> None:
    print(msg, flush=True)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def read_json_file(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def write_json_atomic(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp_path.replace(path)


def append_jsonl(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(data, ensure_ascii=False) + "\n")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def sanitize_narration_text(text: str) -> str:
    """Strip common annotation artifacts that TTS would read aloud."""
    text = text.replace("\u00a0", " ")
    # Remove markdown-like emphasis markers and common stage directions.
    text = re.sub(r"\*\s*(?:brief|short|tiny|slight)?\s*(?:pause|breath|beat|silence|whisper|laugh|sigh)\s*\*", " ", text, flags=re.I)
    text = re.sub(r"\((?:\s*(?:brief|short|tiny|slight)?\s*(?:pause|breath|beat|silence|whisper|laugh|sigh)[^)]*)\)", " ", text, flags=re.I)
    text = re.sub(r"\[(?:\s*(?:brief|short|tiny|slight)?\s*(?:pause|breath|beat|silence|whisper|laugh|sigh)[^]]*)\]", " ", text, flags=re.I)
    text = re.sub(r"\b(?:brief|short|tiny|slight)\s+(?:pause|breath|beat|silence|whisper|laugh|sigh)\b", " ", text, flags=re.I)
    text = re.sub(r"[\*_]", "", text)
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


LOCAL_7B_REWRITE_PROMPT = textwrap.dedent(
    """
    You are normalizing extracted book text for audiobook narration.
    This is NOT a question-answer task and NOT a completion task.
    Your only job is to output a cleaned version of the provided text.

    Rule 1: Never add information that is not explicitly present.
    Rule 2: Never explain, summarize, continue, or answer the text.
    Rule 3: If the input is short, title-like, table-of-contents-like, list-like, imperative, fragmentary, or ambiguous, return it unchanged except for trivial whitespace cleanup.
    Rule 4: Preserve numbering, capitalization, quoted names, and unusual phrasing unless there is an obvious typo.
    Rule 5: Keep the original meaning, facts, names, numbers, and wording as much as possible.
    Rule 6: Only make tiny punctuation or spacing fixes when necessary for speech.
    Rule 7: If unsure, copy the input exactly.

    Return only the cleaned text between <out> tags.

    Example A input: PLOT SYNOPSIS
    Example A output: <out>PLOT SYNOPSIS</out>

    Example B input: Compare two washing machines for overall value.
    Example B output: <out>Compare two washing machines for overall value.</out>

    Example C input: 22. EXPERT INTUITION: WHEN CAN WE TRUST IT?
    Example C output: <out>22. EXPERT INTUITION: WHEN CAN WE TRUST IT?</out>
    """
).strip()


def cleanup_preserved_text(text: str) -> str:
    text = text.replace("\u00a0", " ")
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def normalize_narration_chunk(text: str) -> str:
    """Deterministic cleanup that is safe to apply without an LLM."""
    text = cleanup_preserved_text(text)
    # Remove spaces before punctuation.
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)
    # Tighten spaces just inside brackets/parentheses.
    text = re.sub(r"([\[(])\s+", r"\1", text)
    text = re.sub(r"\s+([\])])", r"\1", text)
    # Normalize repeated internal spacing one more time after punctuation fixes.
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def apply_tts_pronunciation_glossary(text: str) -> str:
    """Apply small, conservative TTS-only pronunciation nudges.

    These substitutions are intentionally narrow and are applied only to the
    text sent to speech synthesis, not as source-text rewrites.
    """
    normalized = text

    pronunciation_rules = [
        # Past/past-participle `read` -> nudge TTS toward "red".
        (r"\bhaving read\b", "having red"),
        (r"\bhad read\b", "had red"),
        (r"\bhas read\b", "has red"),
        (r"\bhave read\b", "have red"),
        (r"\bwas read\b", "was red"),
        (r"\bwere read\b", "were red"),
        (r"\bis read\b", "is red"),
        (r"\bbe read by\b", "be red by"),
        (r"\bread by\b", "red by"),
        (r"\bas you read the\b", "as you red the"),
        (r"\bwhen you read the\b", "when you red the"),
        (r"\bafter you read\b", "after you red"),
    ]

    for pattern, replacement in pronunciation_rules:
        normalized = re.sub(pattern, replacement, normalized, flags=re.I)
    return normalized


# HLS SEGMENT FUNCTIONS ---------------------------------------------------------


def write_wav_from_float32(path: Path, audio: np.ndarray, sample_rate: int = 24000) -> None:
    """Write raw float32 audio array to WAV file at given sample rate."""
    import wave
    audio_int16 = (audio * 32767).astype(np.int16)
    with wave.open(str(path), "w") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(audio_int16.tobytes())


def write_m4a_segment(audio: np.ndarray, path: Path, sample_rate: int = 24000) -> None:
    """Write audio segment as AAC in M4A container for HLS."""
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        return
    import tempfile
    wav_tmp = path.with_suffix(".tmp.wav")
    write_wav_from_float32(wav_tmp, audio, sample_rate)
    cmd = [
        "ffmpeg", "-y", "-i", str(wav_tmp),
        "-c:a", "aac", "-b:a", "128k", "-f", "ipod", str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    wav_tmp.unlink(missing_ok=True)


def encode_wav_to_m4a(input_path: Path, output_path: Path, bitrate: str = "128k") -> None:
    """Encode a WAV file to AAC in an M4A container (fragmented MP4 for HLS compatibility)."""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists() and output_path.stat().st_size > 0:
        return
    cmd = [
        "ffmpeg", "-y", "-i", str(input_path),
        "-c:a", "aac", "-b:a", bitrate,
        "-f", "mp4", "-movflags", "frag_keyframe+empty_moov+default_base_moof",
        str(output_path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)


def append_to_m3u8(playlist_path: Path, segment_name: str, duration_s: float) -> None:
    """Append a segment entry to an M3U8 playlist, creating if needed."""
    playlist_path.parent.mkdir(parents=True, exist_ok=True)
    with open(playlist_path, "a", encoding="utf-8") as f:
        if playlist_path.stat().st_size == 0:
            f.write("#EXTM3U\n")
            f.write("#EXT-X-VERSION:3\n")
            f.write("#EXT-X-TARGETDURATION:60\n")
            f.write("#EXT-X-PLAYLIST-TYPE:EVENT\n")
        f.write(f"#EXTINF:{duration_s:.3f},\n")
        f.write(f"{segment_name}\n")


def finalize_m3u8(playlist_path: Path) -> None:
    """Add end marker to completed M3U8 playlist."""
    if playlist_path.exists():
        existing = playlist_path.read_text(encoding="utf-8")
        if existing.rstrip().endswith("#EXT-X-ENDLIST"):
            return
    with open(playlist_path, "a", encoding="utf-8") as f:
        f.write("#EXT-X-ENDLIST\n")


def ensure_hls_gap_segment(gap_wav_path: Path, gap_m4a_path: Path, sample_rate: int) -> float:
    """Ensure a silence gap exists in both WAV and HLS segment form and return its duration."""
    gap_seconds = 1.75 if gap_wav_path.name == "chunk-000-gap.wav" else 0.45
    if not (gap_wav_path.exists() and gap_wav_path.stat().st_size > 44):
        make_silence_wav(gap_wav_path, seconds=gap_seconds, sample_rate=sample_rate)
    encode_wav_to_m4a(gap_wav_path, gap_m4a_path)
    return wav_duration_seconds(gap_wav_path)


def rebuild_hls_playlist(chapter_dir: Path, playlist_path: Path, chapter_index: int, chunk_count: int, sample_rate: int) -> None:
    """Rebuild a chapter HLS playlist so it mirrors the final WAV ordering, including silence gaps."""
    entries = []

    lead_gap_wav = chapter_dir / "chunk-000-gap.wav"
    lead_gap_m4a = chapter_dir / f"chapter-{chapter_index:03d}-gap-000.m4a"
    lead_gap_duration = ensure_hls_gap_segment(lead_gap_wav, lead_gap_m4a, sample_rate)
    entries.append((lead_gap_m4a.name, lead_gap_duration))

    for i in range(1, chunk_count + 1):
        chunk_wav = chapter_dir / f"chunk-{i:03d}.wav"
        if not (chunk_wav.exists() and chunk_wav.stat().st_size > 44):
            continue
        chunk_m4a = chapter_dir / f"chunk-{i:03d}.m4a"
        encode_wav_to_m4a(chunk_wav, chunk_m4a)
        entries.append((chunk_m4a.name, wav_duration_seconds(chunk_wav)))
        if i < chunk_count:
            gap_wav = chapter_dir / f"chunk-{i:03d}-gap.wav"
            gap_m4a = chapter_dir / f"chapter-{chapter_index:03d}-gap-{i:03d}.m4a"
            gap_duration = ensure_hls_gap_segment(gap_wav, gap_m4a, sample_rate)
            entries.append((gap_m4a.name, gap_duration))

    with open(playlist_path, "w", encoding="utf-8") as f:
        f.write("#EXTM3U\n")
        f.write("#EXT-X-VERSION:3\n")
        f.write("#EXT-X-TARGETDURATION:60\n")
        f.write("#EXT-X-PLAYLIST-TYPE:EVENT\n")
        for name, dur in entries:
            f.write(f"#EXTINF:{dur:.3f},\n")
            f.write(f"{name}\n")


def update_live_hls_playlist(chapter_dir: Path, playlist_path: Path, chapter_index: int, chunk_index: int, chunk_count: int, sample_rate: int) -> None:
    """Append the next canonical live-playback entries, including silence gaps before the current chunk."""
    if chunk_index == 1:
        lead_gap_wav = chapter_dir / "chunk-000-gap.wav"
        lead_gap_m4a = chapter_dir / f"chapter-{chapter_index:03d}-gap-000.m4a"
        lead_gap_duration = ensure_hls_gap_segment(lead_gap_wav, lead_gap_m4a, sample_rate)
        append_to_m3u8(playlist_path, lead_gap_m4a.name, lead_gap_duration)
    elif chunk_index <= chunk_count:
        prior_gap_wav = chapter_dir / f"chunk-{chunk_index - 1:03d}-gap.wav"
        prior_gap_m4a = chapter_dir / f"chapter-{chapter_index:03d}-gap-{chunk_index - 1:03d}.m4a"
        prior_gap_duration = ensure_hls_gap_segment(prior_gap_wav, prior_gap_m4a, sample_rate)
        append_to_m3u8(playlist_path, prior_gap_m4a.name, prior_gap_duration)

    chunk_wav = chapter_dir / f"chunk-{chunk_index:03d}.wav"
    chunk_m4a = chapter_dir / f"chunk-{chunk_index:03d}.m4a"
    if chunk_wav.exists() and chunk_wav.stat().st_size > 44:
        encode_wav_to_m4a(chunk_wav, chunk_m4a)
        append_to_m3u8(playlist_path, chunk_m4a.name, wav_duration_seconds(chunk_wav))


def looks_like_table_of_contents(title: str, source: str, text: str) -> bool:
    title_norm = normalize_text(title).strip().lower()
    source_norm = (source or "").strip().lower()
    text_norm = cleanup_preserved_text(text)
    text_lower = text_norm.lower()
    lines = [line.strip() for line in text_norm.splitlines() if line.strip()]

    if title_norm in {"contents", "table of contents", "toc"}:
        return True
    if any(token in source_norm for token in ("toc", "contents", "nav", "ncx")):
        return True
    if text_lower.startswith("table of contents") or text_lower == "contents":
        return True

    toc_line_like = 0
    for line in lines[:80]:
        if re.search(r"\.{2,}\s*\d+$", line):
            toc_line_like += 1
            continue
        if re.match(r"^(chapter|part|introduction|preface|appendix)\b.*\d+$", line, flags=re.I):
            toc_line_like += 1
            continue
        if re.match(r"^\d+[.)]?\s+.+", line) and len(line.split()) <= 14:
            toc_line_like += 1
            continue

    return len(lines) > 0 and toc_line_like >= max(3, len(lines) // 2)


def looks_like_short_heading_or_fragment(text: str) -> bool:
    candidate = cleanup_preserved_text(text)
    if not candidate:
        return True

    words = re.findall(r"\b\w+[\w'’-]*\b", candidate)
    word_count = len(words)
    line_count = len([line for line in candidate.splitlines() if line.strip()])
    alpha_words = [w for w in words if re.search(r"[A-Za-z]", w)]
    upper_ratio = (
        sum(1 for w in alpha_words if w.upper() == w) / len(alpha_words)
        if alpha_words
        else 0.0
    )

    toc_like = bool(re.fullmatch(r"\d+[.)]?\s+[A-Z0-9 ,;:'?!\-–—]+", candidate))
    all_caps_heading = word_count <= 12 and upper_ratio >= 0.8
    short_fragment = word_count <= 8 and len(candidate) <= 80
    very_short = word_count <= 4 and len(candidate) <= 120
    imperative_like = bool(re.match(r"^(compare|describe|explain|list|summarize|outline|write|discuss|identify|consider)\b", candidate, flags=re.I))
    title_case_heading = line_count == 1 and word_count <= 10 and candidate == candidate.title() and candidate[-1:] not in ".!?"

    return any([toc_like, all_caps_heading, short_fragment, very_short, imperative_like, title_case_heading])


def extract_tagged_output(text: str) -> str:
    match = re.search(r"<out>(.*?)</out>", text, flags=re.S | re.I)
    if match:
        return match.group(1).strip()
    return text.strip()


def selective_rewrite_decision(text: str) -> Tuple[bool, str]:
    """Decide whether a chunk is likely to benefit from LLM rewriting."""
    candidate = normalize_narration_chunk(text)
    if not candidate:
        return False, "empty_after_cleanup"
    if looks_like_short_heading_or_fragment(candidate):
        return False, "short_or_heading"

    score = 0
    reasons: List[str] = []
    sentence_breaks = len(re.findall(r"(?<!\d)[.!?](?:\s|$)", candidate))
    words = re.findall(r"\b\w+[\w'’-]*\b", candidate)

    if len(candidate) >= 600:
        score += 1
        reasons.append("long_chunk")
    if len(candidate) >= 900:
        score += 1
        reasons.append("very_long_chunk")
    if len(words) >= 120:
        score += 1
        reasons.append("dense_chunk")
    if sentence_breaks <= 1 and len(candidate) >= 350:
        score += 2
        reasons.append("few_sentence_breaks")
    if re.search(r"(?<=[.!?])\s+[a-z]", candidate):
        score += 2
        reasons.append("lowercase_after_sentence_end")
    if candidate.count("(") != candidate.count(")"):
        score += 1
        reasons.append("unbalanced_parentheses")
    if candidate.count('"') % 2 == 1:
        score += 1
        reasons.append("unbalanced_quotes")

    use_llm = score >= 2
    return use_llm, ",".join(reasons) if reasons else "deterministic_cleanup_only"


def parse_chapter_selection(spec: Optional[str], chapters: List[Chapter]) -> List[Chapter]:
    if not spec:
        return chapters

    selected: List[int] = []
    for part in [p.strip() for p in spec.split(",") if p.strip()]:
        if "-" in part:
            start_str, end_str = part.split("-", 1)
            start = int(start_str)
            end = int(end_str)
            if end < start:
                start, end = end, start
            selected.extend(range(start, end + 1))
        else:
            selected.append(int(part))

    selected_set = set(selected)
    filtered = [ch for ch in chapters if ch.index in selected_set]
    if not filtered:
        raise ValueError(f"No chapters matched selection: {spec}")
    return filtered


def _openrouter_chat_completion(payload: dict, *, timeout: int = 120, attempts: int = 3) -> dict:
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY not set in environment")

    req = urllib.request.Request(
        "https://openrouter.ai/api/v1/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
            return json.loads(raw.decode("utf-8"))
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, ValueError, OSError) as exc:
            last_error = exc
            if attempt < attempts:
                delay = min(2 ** (attempt - 1), 8)
                log(f"⚠️ OpenRouter request failed (attempt {attempt}/{attempts}): {exc}. Retrying in {delay}s …")
                time.sleep(delay)
            else:
                break
    assert last_error is not None
    raise last_error


def rewrite_with_gpt(text: str) -> str:
    """Send text to OpenRouter gpt-oss-120b and get a narrated version."""
    payload = {
        "model": "openai/gpt-oss-120b:free",
        "messages": [
            {
                "role": "system",
                "content": (
                    "You rewrite prose for audiobook narration. Return plain prose only. "
                    "Keep the original meaning, facts, names, and wording as much as possible. "
                    "You may make small punctuation and paragraph-flow changes for spoken delivery. "
                    "Do NOT add greetings, commentary, labels, markdown, asterisks, bracketed notes, "
                    "parenthetical stage directions, sound effects, or explicit pause/breath instructions. "
                    "Do NOT mention the reader or narrator. Output only the rewritten passage."
                )
            },
            {"role": "user", "content": text},
        ],
        "max_tokens": 2048,
        "temperature": 0.2,
    }
    try:
        data = _openrouter_chat_completion(payload)
        content = data["choices"][0]["message"]["content"]
        return sanitize_narration_text(content)
    except Exception as exc:
        log(f"⚠️ GPT rewrite failed; continuing with original text for this chapter chunk: {exc}")
        return sanitize_narration_text(text)


def rewrite_with_local_7b(text: str, *, llm) -> str:
    """Rewrite narration text locally with a loaded llama.cpp model."""
    if looks_like_short_heading_or_fragment(text):
        return cleanup_preserved_text(text)

    user_text = f"<text>\n{text}\n</text>"
    resp = llm.create_chat_completion(
        messages=[
            {"role": "system", "content": LOCAL_7B_REWRITE_PROMPT},
            {"role": "user", "content": user_text},
        ],
        max_tokens=160,
        temperature=0.0,
        top_p=0.9,
    )
    content = extract_tagged_output(resp["choices"][0]["message"]["content"])
    return sanitize_narration_text(content)


def slugify(text: str, limit: int = 80) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return (text[:limit] or "chapter").strip("-")


def normalize_text(text: str) -> str:
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    # Join hyphenated line breaks from EPUB line wrapping.
    text = re.sub(r"(\w)-\n(\w)", r"\1\2", text)
    # Convert single newlines inside paragraphs to spaces, keep blank lines.
    text = re.sub(r"(?<!\n)\n(?!\n)", " ", text)
    # Collapse whitespace.
    text = re.sub(r"[\t\f\v ]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n\s*\n", "\n\n", text)
    # Remove common page-number only lines.
    lines = []
    for line in text.split("\n"):
        if re.fullmatch(r"\s*\d+\s*", line):
            continue
        lines.append(line.strip())
    text = "\n".join(lines)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text


def html_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "xml")
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()
    body = soup.body or soup

    block_tags = {
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "p",
        "li",
        "blockquote",
        "figcaption",
    }
    blocks: List[str] = []
    for tag in body.find_all(block_tags):
        if tag.find_parent(block_tags):
            continue
        text = normalize_text(tag.get_text(" ", strip=True))
        if text:
            blocks.append(text)

    if blocks:
        return normalize_text("\n\n".join(blocks))

    # Fallback for unusually structured documents.
    return normalize_text(body.get_text("\n", strip=True))


def strip_leading_heading(text: str, title: str) -> str:
    lines = [line.strip() for line in text.split("\n") if line.strip()]
    if not lines:
        return text

    title_norm = normalize_text(title).strip().lower()
    if not title_norm:
        return text

    first = normalize_text(lines[0]).strip().lower()
    # Remove exact heading lines or simple variants like "Chapter 1" vs "CHAPTER 1".
    if first == title_norm or first.rstrip(".:") == title_norm.rstrip(".:"):
        return "\n\n".join(lines[1:]).strip()

    # Also strip a repeated heading if the chapter text starts with the title followed by the body.
    joined = normalize_text(text).strip()
    if joined.lower().startswith(title_norm):
        remainder = joined[len(title_norm):].lstrip(" .:\n\t")
        if remainder:
            return remainder
    return text


def extract_chapters(epub_path: Path) -> Tuple[str, List[Chapter]]:
    book = epub.read_epub(str(epub_path))
    title_meta = book.get_metadata("DC", "title")
    book_title = title_meta[0][0] if title_meta else epub_path.stem

    items = [item for item in book.get_items_of_type(ITEM_DOCUMENT)]
    # Preserve spine order when possible.
    spine_ids = [item_id for item_id, _ in book.spine if item_id not in (None, "nav")]
    if spine_ids:
        lookup = {item.get_id(): item for item in items}
        ordered = [lookup[item_id] for item_id in spine_ids if item_id in lookup]
        # Include leftover doc items not in spine.
        seen = {item.get_id() for item in ordered}
        ordered.extend([item for item in items if item.get_id() not in seen])
        items = ordered

    chapters: List[Chapter] = []
    for idx, item in enumerate(items, start=1):
        raw = item.get_content().decode("utf-8", errors="ignore")
        text = html_to_text(raw)
        if not text:
            continue

        # Title heuristics: prefer structured headings from the XHTML itself.
        soup = BeautifulSoup(raw, "xml")
        heading = None
        headings = [
            normalize_text(tag.get_text(" ", strip=True))
            for tag in soup.find_all(["h1", "h2", "h3"])
            if tag and tag.get_text(strip=True)
        ]
        headings = [h for h in headings if h]
        if len(headings) >= 2 and re.fullmatch(r"\d+", headings[0]):
            heading = f"{headings[0]} {headings[1]}"
        elif headings:
            heading = headings[0]
        else:
            title_tag = soup.find("title")
            if title_tag and title_tag.get_text(strip=True):
                heading = normalize_text(title_tag.get_text(" ", strip=True))
        title = heading or Path(item.file_name or f"chapter-{idx}").stem
        title = normalize_text(title).split("\n")[0]
        title = title[:120].strip() or f"Chapter {idx}"
        text = strip_leading_heading(text, title)
        if looks_like_table_of_contents(title, item.file_name or item.get_id(), text):
            log(f"↷ Skipping table-of-contents-like document: {title}")
            continue

        chapters.append(
            Chapter(index=len(chapters) + 1, title=title, source=item.file_name or item.get_id(), text=text)
        )

    if not chapters:
        raise RuntimeError("No readable chapter-like documents were found in the EPUB.")
    return book_title, chapters


_sentence_re = re.compile(r"(?<=[.!?])\s+")
_clause_re = re.compile(r"(?<=[;:])\s+|\s+[—–-]\s+")


def split_sentence_like_units(paragraph: str) -> List[str]:
    sentence_parts = _sentence_re.split(paragraph.strip())
    units: List[str] = []
    for part in sentence_parts:
        part = part.strip()
        if not part:
            continue
        clauses = [c.strip() for c in _clause_re.split(part) if c.strip()]
        if clauses:
            units.extend(clauses)
        else:
            units.append(part)
    return units


def split_long_paragraph(paragraph: str, max_chars: int, soft_chars: Optional[int] = None) -> List[str]:
    units = split_sentence_like_units(paragraph)
    if not units:
        return []

    soft_limit = min(max_chars, soft_chars or max(220, max_chars // 2))
    chunks: List[str] = []
    buf = ""
    for unit in units:
        if not buf:
            buf = unit
            continue

        candidate = f"{buf} {unit}"
        if len(candidate) <= soft_limit:
            buf = candidate
            continue

        if len(candidate) <= max_chars and len(buf) < max(140, soft_limit // 2):
            buf = candidate
            continue

        chunks.append(buf)
        buf = unit

    if buf:
        chunks.append(buf)
    return chunks


def chunk_text(text: str, max_chars: int = 650) -> List[str]:
    paras = [p.strip() for p in text.split("\n\n") if p.strip()]
    chunks: List[str] = []
    soft_chars = min(360, max(220, int(max_chars * 0.55)))

    for para in paras:
        para_chunks = split_long_paragraph(para, max_chars=max_chars, soft_chars=soft_chars)
        if not para_chunks:
            continue
        chunks.extend(para_chunks)
    return chunks


def run(cmd: List[str], *, input_text: Optional[str] = None) -> None:
    log("$ " + " ".join(cmd))
    subprocess.run(
        cmd,
        input=(input_text.encode("utf-8") if input_text is not None else None),
        check=True,
    )


def process_chunks_pipelined(items, producer_fn, consumer_fn, *, max_buffer: int = 1):
    """Run a single producer in a background thread while consuming in order.

    This keeps the pipeline narrow: one chunk can be rewritten while the previous
    chunk is being synthesized, without spawning extra model copies.
    """
    sentinel = object()
    queue: Queue = Queue(maxsize=max_buffer)
    producer_error: list[BaseException] = []

    def producer() -> None:
        try:
            for item in items:
                queue.put((item, producer_fn(item)))
        except BaseException as exc:  # noqa: BLE001 - surface exact failure later
            producer_error.append(exc)
        finally:
            queue.put((sentinel, None))

    thread = threading.Thread(target=producer, daemon=True)
    thread.start()

    results = []
    while True:
        item, produced = queue.get()
        if item is sentinel:
            break
        results.append(consumer_fn(item, produced))

    thread.join()
    if producer_error:
        raise producer_error[0]
    return results


def write_wav_from_float32(path: Path, audio: np.ndarray, sample_rate: int = 24000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    clipped = np.clip(audio, -1.0, 1.0)
    pcm16 = (clipped * 32767.0).astype(np.int16)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(pcm16.tobytes())


def synthesize_chunk_piper(
    text: str,
    wav_path: Path,
    model: Path,
    config: Path,
    piper_bin: str,
) -> None:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    text_path = wav_path.with_suffix(".txt")
    text_path.write_text(text.strip() + "\n", encoding="utf-8")
    tts_text = apply_tts_pronunciation_glossary(text).strip()
    tts_text_path = wav_path.with_suffix(".tts.txt")
    tts_text_path.write_text(tts_text + "\n", encoding="utf-8")
    if wav_path.exists() and wav_path.stat().st_size > 44:
        log(f"[skip] {wav_path.name}")
        return
    cmd = [
        piper_bin,
        "-m",
        str(model),
        "-c",
        str(config),
        "-i",
        str(tts_text_path),
        "-f",
        str(wav_path),
    ]
    run(cmd)


_KOKORO_PIPELINE_CACHE: dict[tuple[str, str], object] = {}


def get_kokoro_pipeline(*, voice: str, language: Optional[str], repo_id: str):
    from kokoro import KPipeline

    kokoro_language = language or voice[:1]
    cache_key = (kokoro_language, repo_id)
    pipeline = _KOKORO_PIPELINE_CACHE.get(cache_key)
    if pipeline is None:
        log(f"🎙️ Loading Kokoro pipeline once for lang={kokoro_language!r}, repo={repo_id!r} …")
        pipeline = KPipeline(lang_code=kokoro_language, repo_id=repo_id)
        _KOKORO_PIPELINE_CACHE[cache_key] = pipeline
    return pipeline


def synthesize_chunk_kokoro(
    text: str,
    wav_path: Path,
    *,
    voice: str,
    language: Optional[str],
    speed: float,
    repo_id: str,
    pipeline=None,
    hls_segment_path: Optional[Path] = None,
) -> None:
    wav_path.parent.mkdir(parents=True, exist_ok=True)
    text_path = wav_path.with_suffix(".txt")
    text_path.write_text(text.strip() + "\n", encoding="utf-8")
    tts_text = apply_tts_pronunciation_glossary(text).strip()
    tts_text_path = wav_path.with_suffix(".tts.txt")
    tts_text_path.write_text(tts_text + "\n", encoding="utf-8")
    if wav_path.exists() and wav_path.stat().st_size > 44:
        log(f"[skip] {wav_path.name}")
        return

    if pipeline is None:
        pipeline = get_kokoro_pipeline(voice=voice, language=language, repo_id=repo_id)

    audio_parts: List[np.ndarray] = []
    for result in pipeline(tts_text, voice=voice, speed=speed, split_pattern=r"\n+"):
        if result.audio is None:
            continue
        audio_parts.append(result.audio.detach().cpu().numpy())
    if not audio_parts:
        raise RuntimeError(f"Kokoro produced no audio for {wav_path.name}")
    audio = np.concatenate(audio_parts)
    write_wav_from_float32(wav_path, audio, sample_rate=24000)
    
    # Also write HLS segment if path provided
    if hls_segment_path:
        write_m4a_segment(audio, hls_segment_path, sample_rate=24000)


_KOKORO_WORKER_PIPELINE = None


def init_kokoro_worker(voice: str, language: Optional[str], repo_id: str) -> None:
    global _KOKORO_WORKER_PIPELINE
    _KOKORO_WORKER_PIPELINE = get_kokoro_pipeline(voice=voice, language=language, repo_id=repo_id)


def synthesize_chunk_kokoro_job(args):
    text, wav_path_str, voice, language, speed, repo_id = args
    wav_path = Path(wav_path_str)
    start = time.perf_counter()
    synthesize_chunk_kokoro(
        text,
        wav_path,
        voice=voice,
        language=language,
        speed=speed,
        repo_id=repo_id,
        pipeline=_KOKORO_WORKER_PIPELINE,
    )
    return {
        "wav_path": str(wav_path),
        "elapsed_s": time.perf_counter() - start,
        "bytes": wav_path.stat().st_size if wav_path.exists() else 0,
    }


def synthesize_chunk_kokoro_job_with_hls(args):
    """Same as regular job but also writes HLS segment for live playback."""
    import numpy as np
    wav_path_str, text, voice, language, speed, repo_id = args
    wav_path = Path(wav_path_str)
    
    # Run normal synthesis first
    result = synthesize_chunk_kokoro_job([text, wav_path_str, voice, language, speed, repo_id])
    
    # Then write HLS segment immediately
    if wav_path.exists():
        # Get audio data back from WAV
        import soundfile as sf
        audio, sr = sf.read(wav_path)
        m4a_path = wav_path.with_suffix(".m4a")
        write_m4a_segment(audio, m4a_path, sample_rate=sr)
        result["m4a_path"] = str(m4a_path)
    
    return result


def make_silence_wav(path: Path, seconds: float = 1.75, sample_rate: int = 22050) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and path.stat().st_size > 44:
        return
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"anullsrc=r={sample_rate}:cl=mono",
        "-t",
        str(seconds),
        "-c:a",
        "pcm_s16le",
        str(path),
    ]
    run(cmd)


def wav_duration_seconds(path: Path) -> float:
    with wave.open(str(path), "rb") as wf:
        frames = wf.getnframes()
        rate = wf.getframerate()
    return frames / float(rate)


def _ffconcat_quote(path: Path) -> str:
    # ffconcat expects single-quoted paths; escape embedded single quotes.
    return "'" + path.as_posix().replace("'", "'\\''") + "'"


def ffmpeg_concat(inputs: List[Path], output: Path) -> None:
    if len(inputs) == 1:
        output.write_bytes(inputs[0].read_bytes())
        return
    concat_list = output.with_suffix(".concat.txt")
    concat_list.write_text(
        "\n".join([f"file {_ffconcat_quote(p.resolve())}" for p in inputs]) + "\n",
        encoding="utf-8",
    )
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-c",
        "copy",
        str(output),
    ]
    run(cmd)


def build_ffmetadata(chapters: List[Chapter], durations: List[float], title: str) -> str:
    lines = [";FFMETADATA1", f"title={title}"]
    start_ms = 0
    for ch, dur in zip(chapters, durations):
        end_ms = start_ms + max(1, int(dur * 1000))
        lines.extend(
            [
                "[CHAPTER]",
                "TIMEBASE=1/1000",
                f"START={start_ms}",
                f"END={end_ms}",
                f"title={ch.title}",
            ]
        )
        start_ms = end_ms
    return "\n".join(lines) + "\n"


def encode_m4b(chapter_wavs: List[Path], chapters: List[Chapter], title: str, out_m4b: Path) -> None:
    concat_list = out_m4b.with_suffix(".chapters.txt")
    concat_list.write_text(
        "\n".join([f"file {_ffconcat_quote(p.resolve())}" for p in chapter_wavs]) + "\n",
        encoding="utf-8",
    )
    durations = [wav_duration_seconds(p) for p in chapter_wavs]
    metadata = out_m4b.with_suffix(".ffmetadata")
    metadata.write_text(build_ffmetadata(chapters, durations, title), encoding="utf-8")
    cmd = [
        "ffmpeg",
        "-y",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(concat_list),
        "-i",
        str(metadata),
        "-map_metadata",
        "1",
        "-map_chapters",
        "1",
        "-c:a",
        "aac",
        "-b:a",
        "96k",
        str(out_m4b),
    ]
    run(cmd)


def process_book(
    epub_path: Path,
    outdir: Path,
    tts_engine: str,
    rewrite_backend: str,
    rewrite_policy: str,
    rewrite_repo_id: str,
    rewrite_filename: str,
    rewrite_n_ctx: int,
    rewrite_n_threads: int,
    rewrite_n_batch: int,
    piper_model: Path,
    piper_config: Path,
    piper_bin: str,
    kokoro_voice: str,
    kokoro_language: Optional[str],
    kokoro_repo_id: str,
    kokoro_speed: float,
    max_chars: int,
    kokoro_workers: int,
    mode: str = "full",
    chapter_selection: Optional[str] = None,
) -> Path:
    title, chapters = extract_chapters(epub_path)
    chapters = parse_chapter_selection(chapter_selection, chapters)
    chapter_batches = [(ch, chunk_text(ch.text, max_chars=max_chars)) for ch in chapters]
    total_chunks = sum(len(chunks) for _, chunks in chapter_batches)
    selective_llm_chunk_count = 0
    if rewrite_policy == "selective":
        selective_llm_chunk_count = sum(
            1
            for _, chunks in chapter_batches
            for chunk in chunks
            if selective_rewrite_decision(chunk)[0]
        )

    book_dir = outdir / slugify(title)
    chunks_dir = book_dir / "chunks"
    chapter_dir = book_dir / "chapters"
    book_dir.mkdir(parents=True, exist_ok=True)
    chunks_dir.mkdir(exist_ok=True)
    chapter_dir.mkdir(exist_ok=True)

    manifest_path = book_dir / "manifest.json"
    manifest = {
        "title": title,
        "source": str(epub_path),
        "mode": mode,
        "chapter_selection": chapter_selection,
        "tts_engine": tts_engine,
        "rewrite_backend": rewrite_backend,
        "rewrite_policy": rewrite_policy,
        "rewrite_repo_id": rewrite_repo_id,
        "rewrite_filename": rewrite_filename,
        "rewrite_n_ctx": rewrite_n_ctx,
        "rewrite_n_threads": rewrite_n_threads,
        "rewrite_n_batch": rewrite_n_batch,
        "voice_model": str(piper_model),
        "voice_config": str(piper_config),
        "kokoro_voice": kokoro_voice,
        "kokoro_language": kokoro_language,
        "kokoro_repo_id": kokoro_repo_id,
        "kokoro_speed": kokoro_speed,
        "kokoro_workers": kokoro_workers,
        "max_chars": max_chars,
        "chapters": [],
    }
    run_started_wall = time.perf_counter()
    started_at = utc_now_iso()
    status_path = book_dir / "status.json"
    events_path = book_dir / "events.jsonl"

    status = {
        "title": title,
        "source": str(epub_path),
        "book_dir": str(book_dir),
        "mode": mode,
        "chapter_selection": chapter_selection,
        "tts_engine": tts_engine,
        "rewrite_backend": rewrite_backend,
        "rewrite_policy": rewrite_policy,
        "rewrite_repo_id": rewrite_repo_id,
        "rewrite_filename": rewrite_filename,
        "rewrite_n_ctx": rewrite_n_ctx,
        "rewrite_n_threads": rewrite_n_threads,
        "rewrite_n_batch": rewrite_n_batch,
        "kokoro_voice": kokoro_voice,
        "kokoro_language": kokoro_language,
        "kokoro_repo_id": kokoro_repo_id,
        "kokoro_speed": kokoro_speed,
        "kokoro_workers": kokoro_workers,
        "started_at": started_at,
        "updated_at": started_at,
        "phase": "initializing",
        "error": None,
        "output": None,
        "progress": {
            "total_chapters": len(chapter_batches),
            "completed_chapters": 0,
            "total_chunks": total_chunks,
            "rewrite_completed_chunks": 0,
            "tts_completed_chunks": 0,
        },
        "current": {
            "chapter_index": None,
            "chapter_title": None,
            "chapter_slug": None,
            "chunk_index": None,
            "chunk_total": None,
            "phase": "initializing",
        },
        "chapters": [
            {
                "index": ch.index,
                "title": ch.title,
                "slug": f"{ch.index:03d}-{slugify(ch.title)}",
                "status": "pending",
                "total_chunks": len(chunks),
                "rewrite_completed_chunks": 0,
                "tts_completed_chunks": 0,
                "rewrite_cache_hits": 0,
                "rewrite_cache_misses": 0,
                "scripted_cleanup_chunks": 0,
                "llm_rewrite_chunks": 0,
                "rewrite_elapsed_s": 0.0,
                "tts_elapsed_s": 0.0,
                "hls_playlist": None,
                "wall_s": 0.0,
                "empty_rewrite_chunks": 0,
            }
            for ch, chunks in chapter_batches
        ],
        "anomalies": [],
    }
    status_by_chapter = {entry["index"]: entry for entry in status["chapters"]}

    def save_status() -> None:
        status["updated_at"] = utc_now_iso()
        status["elapsed_s"] = round(time.perf_counter() - run_started_wall, 3)
        write_json_atomic(status_path, status)

    def emit_event(event_type: str, **data) -> None:
        append_jsonl(
            events_path,
            {
                "ts": utc_now_iso(),
                "event": event_type,
                **data,
            },
        )

    save_status()
    emit_event("run_started", title=title, mode=mode, chapter_selection=chapter_selection, total_chapters=len(chapter_batches), total_chunks=total_chunks, rewrite_policy=rewrite_policy)

    chapter_wavs: List[Path] = []
    gap_sample_rate = 24000 if tts_engine == "kokoro" else 22050
    kokoro_pool = None
    rewrite_llm = None
    if (
        rewrite_backend == "local-7b"
        and rewrite_policy != "script-only"
        and (rewrite_policy != "selective" or selective_llm_chunk_count > 0)
        and mode in {"full", "rewrite-only", "hls-tts"}
    ):
        from llama_cpp import Llama

        status["phase"] = "loading_rewrite_model"
        status["current"]["phase"] = "loading_rewrite_model"
        save_status()
        log(f"🧠 Loading local rewrite model once from {rewrite_repo_id!r} …")
        rewrite_llm = Llama.from_pretrained(
            repo_id=rewrite_repo_id,
            filename=rewrite_filename,
            n_ctx=rewrite_n_ctx,
            n_threads=rewrite_n_threads,
            n_batch=rewrite_n_batch,
            verbose=False,
            chat_format="qwen",
        )
    elif rewrite_policy == "selective" and mode in {"full", "rewrite-only", "hls-tts"} and selective_llm_chunk_count == 0:
        log("🪄 Selective rewrite found no chunks needing LLM rewriting; using deterministic cleanup only.")
    if tts_engine == "kokoro" and kokoro_workers > 1 and mode in {"full", "tts-only", "hls-tts"}:
        status["phase"] = "starting_tts_workers"
        status["current"]["phase"] = "starting_tts_workers"
        save_status()
        log(f"🎛️ Starting {kokoro_workers} persistent Kokoro workers …")
        mp_ctx = mp.get_context("spawn")
        kokoro_pool = mp_ctx.Pool(
            processes=kokoro_workers,
            initializer=init_kokoro_worker,
            initargs=(kokoro_voice, kokoro_language, kokoro_repo_id),
        )

    try:
        for ch, chunks in chapter_batches:
            log(f"\n=== Chapter {ch.index}: {ch.title} ===")
            chapter_wall_start = time.perf_counter()
            chapter_slug = f"{ch.index:03d}-{slugify(ch.title)}"
            ch_dir = chapter_dir / chapter_slug
            ch_dir.mkdir(exist_ok=True)
            chapter_status = status_by_chapter[ch.index]
            chapter_status["status"] = "running"
            status["phase"] = "rewriting" if mode not in {"tts-only", "hls-tts"} else "tts"
            status["current"] = {
                "chapter_index": ch.index,
                "chapter_title": ch.title,
                "chapter_slug": chapter_slug,
                "chunk_index": 0,
                "chunk_total": len(chunks),
                "phase": "rewriting" if mode not in {"tts-only", "hls-tts"} else "tts",
            }
            save_status()
            emit_event("chapter_started", chapter_index=ch.index, chapter_title=ch.title, chapter_slug=chapter_slug, chunk_total=len(chunks))

            silence_wav = ch_dir / "chunk-000-gap.wav"
            make_silence_wav(silence_wav, sample_rate=gap_sample_rate)
            chunk_paths_by_index = {0: silence_wav}
            chapter_cache_path = ch_dir / "rewrite-cache.json"
            chapter_hash = sha256_text(ch.text)
            chapter_cache = read_json_file(
                chapter_cache_path,
                default={"chapter_hash": chapter_hash, "max_chars": max_chars, "rewrite_backend": rewrite_backend, "rewrite_policy": rewrite_policy, "chunks": {}},
            )
            if (
                chapter_cache.get("chapter_hash") != chapter_hash
                or chapter_cache.get("max_chars") != max_chars
                or chapter_cache.get("rewrite_backend") != rewrite_backend
                or chapter_cache.get("rewrite_policy") != rewrite_policy
            ):
                chapter_cache = {
                    "chapter_hash": chapter_hash,
                    "max_chars": max_chars,
                    "rewrite_backend": rewrite_backend,
                    "rewrite_policy": rewrite_policy,
                    "chunks": {},
                }
            chapter_cache.setdefault("chunks", {})

            chapter_stats = {
                "rewrite_cache_hits": 0,
                "rewrite_cache_misses": 0,
                "scripted_cleanup_chunks": 0,
                "llm_rewrite_chunks": 0,
                "rewrite_elapsed_s": 0.0,
                "tts_elapsed_s": 0.0,
                "chunks": [],
            }

            def rewrite_chunk(chunk_index: int, chunk: str):
                raw_hash = sha256_text(chunk)
                cached = chapter_cache["chunks"].get(str(chunk_index))
                if cached and cached.get("raw_sha256") == raw_hash and cached.get("rewritten_text"):
                    chapter_stats["rewrite_cache_hits"] += 1
                    chapter_status["rewrite_cache_hits"] = chapter_stats["rewrite_cache_hits"]
                    llm_used = bool(cached.get("llm_used", False))
                    reason = cached.get("rewrite_reason", "cached")
                    if llm_used:
                        chapter_status["llm_rewrite_chunks"] += 1
                    else:
                        chapter_status["scripted_cleanup_chunks"] += 1
                    log(f"♻️ Reusing rewritten chunk {chunk_index:03d} from cache")
                    return sanitize_narration_text(cached["rewritten_text"]), 0.0, True, llm_used, reason

                deterministic = normalize_narration_chunk(chunk)
                use_llm = rewrite_policy == "full"
                reason = "full_rewrite_policy"
                if rewrite_policy == "script-only":
                    use_llm = False
                    reason = "script_only_policy"
                elif rewrite_policy == "selective":
                    use_llm, reason = selective_rewrite_decision(chunk)

                start = time.perf_counter()
                if use_llm and rewrite_backend == "openrouter":
                    log(f"⚡ Re-writing chunk {chunk_index:03d} with OpenRouter GPT-OSS-120b …")
                    rewritten = rewrite_with_gpt(deterministic)
                elif use_llm and rewrite_backend == "local-7b":
                    log(f"⚡ Re-writing chunk {chunk_index:03d} with local GGUF …")
                    assert rewrite_llm is not None
                    rewritten = rewrite_with_local_7b(deterministic, llm=rewrite_llm)
                else:
                    rewritten = deterministic
                if not rewritten.strip():
                    log(f"⚠️ Rewrite produced empty text for chunk {chunk_index:03d}; falling back to cleaned original text")
                    rewritten = deterministic or sanitize_narration_text(chunk) or cleanup_preserved_text(chunk)
                    use_llm = False
                    reason = f"{reason},empty_fallback"
                elapsed = time.perf_counter() - start
                chapter_stats["rewrite_cache_misses"] += 1
                chapter_stats["rewrite_elapsed_s"] += elapsed
                chapter_status["rewrite_cache_misses"] = chapter_stats["rewrite_cache_misses"]
                chapter_status["rewrite_elapsed_s"] = round(chapter_stats["rewrite_elapsed_s"], 3)
                if use_llm:
                    chapter_stats["llm_rewrite_chunks"] += 1
                    chapter_status["llm_rewrite_chunks"] += 1
                else:
                    chapter_stats["scripted_cleanup_chunks"] += 1
                    chapter_status["scripted_cleanup_chunks"] += 1
                chapter_cache["chunks"][str(chunk_index)] = {
                    "raw_sha256": raw_hash,
                    "rewritten_text": rewritten,
                    "rewrite_elapsed_s": round(elapsed, 3),
                    "llm_used": use_llm,
                    "rewrite_reason": reason,
                }
                write_json_atomic(chapter_cache_path, chapter_cache)
                return rewritten, elapsed, False, use_llm, reason

            synth_jobs = []
            text_paths_by_index = {}
            for i, chunk in enumerate(chunks, start=1):
                text_path = ch_dir / f"chunk-{i:03d}.txt"
                text_paths_by_index[i] = text_path
                chunk_path = ch_dir / f"chunk-{i:03d}.wav"
                chunk_paths_by_index[i] = chunk_path
                status["current"]["chunk_index"] = i

                if mode in {"tts-only"}:
                    if not text_path.exists() or text_path.stat().st_size == 0:
                        raise RuntimeError(f"Missing rewritten text for chapter {ch.index} chunk {i}: {text_path}")
                    rewritten_chunk = sanitize_narration_text(text_path.read_text(encoding="utf-8"))
                    rewrite_elapsed = 0.0
                    cache_hit = True
                    llm_used = False
                    rewrite_reason = "tts_only_reuse"
                else:
                    rewritten_chunk, rewrite_elapsed, cache_hit, llm_used, rewrite_reason = rewrite_chunk(i, chunk)
                    text_path.write_text(rewritten_chunk + "\n", encoding="utf-8")

                if mode not in {"tts-only"}:
                    status["phase"] = "rewriting"
                    status["current"]["phase"] = "rewriting"
                    status["progress"]["rewrite_completed_chunks"] += 1
                    chapter_status["rewrite_completed_chunks"] += 1
                    chapter_status["rewrite_elapsed_s"] = round(chapter_stats["rewrite_elapsed_s"], 3)
                    if not rewritten_chunk.strip():
                        chapter_status["empty_rewrite_chunks"] += 1
                        status["anomalies"].append(
                            {
                                "type": "empty_rewrite_chunk",
                                "chapter_index": ch.index,
                                "chunk_index": i,
                                "text_path": str(text_path),
                            }
                        )
                    save_status()
                    emit_event(
                        "chunk_rewritten",
                        chapter_index=ch.index,
                        chunk_index=i,
                        cache_hit=cache_hit,
                        llm_used=llm_used,
                        rewrite_reason=rewrite_reason,
                        rewrite_elapsed_s=round(rewrite_elapsed, 3),
                        empty=not rewritten_chunk.strip(),
                        text_path=str(text_path),
                    )

                if mode == "rewrite-only":
                    chapter_stats["chunks"].append(
                        {
                            "index": i,
                            "text": str(text_path),
                            "rewrite_elapsed_s": round(rewrite_elapsed, 3),
                            "tts_elapsed_s": 0.0,
                            "cache_hit": cache_hit,
                            "llm_used": llm_used,
                            "rewrite_reason": rewrite_reason,
                        }
                    )
                    continue

                if chunk_path.exists() and chunk_path.stat().st_size > 0:
                    log(f"↩️ Reusing existing chunk: {chunk_path.name}")
                    chapter_stats["chunks"].append(
                        {
                            "index": i,
                            "text": str(text_path),
                            "wav": str(chunk_path),
                            "rewrite_elapsed_s": round(rewrite_elapsed, 3),
                            "tts_elapsed_s": 0.0,
                            "cache_hit": cache_hit,
                        }
                    )
                    status["phase"] = "tts"
                    status["current"]["phase"] = "tts"
                    status["progress"]["tts_completed_chunks"] += 1
                    chapter_status["tts_completed_chunks"] += 1
                    save_status()
                    emit_event("chunk_tts_reused", chapter_index=ch.index, chunk_index=i, wav_path=str(chunk_path))
                    continue

                if tts_engine == "kokoro" and kokoro_pool is not None:
                    synth_jobs.append(
                        {
                            "index": i,
                            "chunk_path": chunk_path,
                            "text_path": str(text_path),
                            "rewrite_elapsed_s": rewrite_elapsed,
                            "cache_hit": cache_hit,
                            "result": kokoro_pool.apply_async(
                                synthesize_chunk_kokoro_job,
                                ((rewritten_chunk, str(chunk_path), kokoro_voice, kokoro_language, kokoro_speed, kokoro_repo_id),),
                            ),
                        }
                    )
                else:
                    status["phase"] = "tts"
                    status["current"]["phase"] = "tts"
                    save_status()
                    synth_start = time.perf_counter()
                    if tts_engine == "kokoro":
                        synthesize_chunk_kokoro(
                            rewritten_chunk,
                            chunk_path,
                            voice=kokoro_voice,
                            language=kokoro_language,
                            speed=kokoro_speed,
                            repo_id=kokoro_repo_id,
                            pipeline=None,
                        )
                    else:
                        synthesize_chunk_piper(
                            rewritten_chunk,
                            chunk_path,
                            model=piper_model,
                            config=piper_config,
                            piper_bin=piper_bin,
                        )
                    synth_elapsed = time.perf_counter() - synth_start
                    chapter_stats["tts_elapsed_s"] += synth_elapsed
                    chapter_status["tts_elapsed_s"] = round(chapter_stats["tts_elapsed_s"], 3)
                    status["progress"]["tts_completed_chunks"] += 1
                    chapter_status["tts_completed_chunks"] += 1
                    
                    # HLS segment output
                    if mode == "hls-tts":
                        hls_playlist = ch_dir / f"chapter-{ch.index:03d}.m3u8"
                        update_live_hls_playlist(ch_dir, hls_playlist, ch.index, i, len(chunks), gap_sample_rate)
                        chapter_status["hls_playlist"] = str(hls_playlist)
                    
                    chapter_stats["chunks"].append(
                        {
                            "index": i,
                            "text": str(text_path),
                            "wav": str(chunk_path),
                            "rewrite_elapsed_s": round(rewrite_elapsed, 3),
                            "tts_elapsed_s": round(synth_elapsed, 3),
                            "cache_hit": cache_hit,
                        }
                    )
                    save_status()
                    emit_event(
                        "chunk_tts_completed",
                        chapter_index=ch.index,
                        chunk_index=i,
                        wav_path=str(chunk_path),
                        tts_elapsed_s=round(synth_elapsed, 3),
                    )

            for job in synth_jobs:
                status["phase"] = "tts"
                status["current"]["phase"] = "tts"
                status["current"]["chunk_index"] = job["index"]
                save_status()
                result = job["result"].get()
                chunk_path = Path(job["chunk_path"])
                chapter_stats["tts_elapsed_s"] += float(result["elapsed_s"])
                chapter_status["tts_elapsed_s"] = round(chapter_stats["tts_elapsed_s"], 3)
                status["progress"]["tts_completed_chunks"] += 1
                chapter_status["tts_completed_chunks"] += 1
                
                # HLS segment output for parallel workers
                if mode == "hls-tts":
                    hls_playlist = ch_dir / f"chapter-{ch.index:03d}.m3u8"
                    update_live_hls_playlist(ch_dir, hls_playlist, ch.index, job["index"], len(chunks), gap_sample_rate)
                    chapter_status["hls_playlist"] = str(hls_playlist)
                
                chapter_stats["chunks"].append(
                    {
                        "index": job["index"],
                        "text": job["text_path"],
                        "wav": str(chunk_path),
                        "rewrite_elapsed_s": round(job["rewrite_elapsed_s"], 3),
                        "tts_elapsed_s": round(float(result["elapsed_s"]), 3),
                        "cache_hit": job["cache_hit"],
                    }
                )
                save_status()
                emit_event(
                    "chunk_tts_completed",
                    chapter_index=ch.index,
                    chunk_index=job["index"],
                    wav_path=str(chunk_path),
                    tts_elapsed_s=round(float(result["elapsed_s"]), 3),
                )

            chapter_stats["chunks"].sort(key=lambda item: item["index"])

            chapter_record = {
                "index": ch.index,
                "title": ch.title,
                "source": ch.source,
                "stats": chapter_stats,
            }

            if mode != "rewrite-only":
                ch.chunk_paths = [silence_wav]
                for i in range(1, len(chunks) + 1):
                    chunk_path = chunk_paths_by_index[i]
                    ch.chunk_paths.append(chunk_path)
                    if i < len(chunks):
                        gap_wav = ch_dir / f"chunk-{i:03d}-gap.wav"
                        if not (gap_wav.exists() and gap_wav.stat().st_size > 0):
                            make_silence_wav(gap_wav, seconds=0.45, sample_rate=gap_sample_rate)
                        ch.chunk_paths.append(gap_wav)

                chapter_wav = chapter_dir / f"{chapter_slug}.wav"
                ffmpeg_concat(ch.chunk_paths, chapter_wav)
                ch.wav_path = chapter_wav
                ch.duration_s = wav_duration_seconds(chapter_wav)
                chapter_m4a = chapter_dir / f"{chapter_slug}.m4a"
                encode_wav_to_m4a(chapter_wav, chapter_m4a, bitrate="96k")
                chapter_wavs.append(chapter_wav)
                chapter_record.update(
                    {
                        "chunks": [str(p) for p in ch.chunk_paths],
                        "wav": str(chapter_wav),
                        "m4a": str(chapter_m4a),
                        "duration_s": ch.duration_s,
                    }
                )
            else:
                chapter_record["texts"] = [str(text_paths_by_index[i]) for i in range(1, len(chunks) + 1)]

            chapter_stats["total_s"] = round(chapter_stats["rewrite_elapsed_s"] + chapter_stats["tts_elapsed_s"], 3)
            chapter_stats["wall_s"] = round(time.perf_counter() - chapter_wall_start, 3)
            chapter_status["status"] = "completed"
            chapter_status["rewrite_elapsed_s"] = round(chapter_stats["rewrite_elapsed_s"], 3)
            chapter_status["tts_elapsed_s"] = round(chapter_stats["tts_elapsed_s"], 3)
            chapter_status["wall_s"] = chapter_stats["wall_s"]
            manifest["chapters"].append(chapter_record)
            write_json_atomic(manifest_path, manifest)
            status["progress"]["completed_chapters"] += 1
            status["current"]["phase"] = "chapter_complete"
            save_status()
            emit_event(
                "chapter_completed",
                chapter_index=ch.index,
                chapter_title=ch.title,
                rewrite_elapsed_s=round(chapter_stats["rewrite_elapsed_s"], 3),
                tts_elapsed_s=round(chapter_stats["tts_elapsed_s"], 3),
                wall_s=chapter_stats["wall_s"],
                empty_rewrite_chunks=chapter_status["empty_rewrite_chunks"],
            )
            log(
                f"📊 Chapter {ch.index} summary: rewrite={chapter_stats['rewrite_elapsed_s']:.1f}s, "
                f"tts={chapter_stats['tts_elapsed_s']:.1f}s, wall={chapter_stats['wall_s']:.1f}s, "
                f"cache_hits={chapter_stats['rewrite_cache_hits']}, cache_misses={chapter_stats['rewrite_cache_misses']}"
            )
            
            # Generate/finalize HLS playlist for live playback
            if mode == "hls-tts":
                hls_playlist = ch_dir / f"chapter-{ch.index:03d}.m3u8"
                rebuild_hls_playlist(ch_dir, hls_playlist, ch.index, len(chunks), gap_sample_rate)
                finalize_m3u8(hls_playlist)
                chapter_record["hls_playlist"] = str(hls_playlist)
                chapter_status["hls_playlist"] = str(hls_playlist)
                write_json_atomic(manifest_path, manifest)
                save_status()
    except Exception as exc:
        status["phase"] = "error"
        status["error"] = str(exc)
        status["current"]["phase"] = "error"
        save_status()
        emit_event("run_failed", error=str(exc))
        raise
    finally:
        if kokoro_pool is not None:
            kokoro_pool.close()
            kokoro_pool.join()

    if mode == "rewrite-only":
        manifest["output"] = str(book_dir)
        write_json_atomic(manifest_path, manifest)
        status["phase"] = "done"
        status["current"]["phase"] = "done"
        status["output"] = str(book_dir)
        save_status()
        emit_event("run_completed", output=str(book_dir))
        return book_dir

    out_m4b = book_dir / f"{slugify(title)}.m4b"
    status["phase"] = "encoding"
    status["current"]["phase"] = "encoding"
    save_status()
    encode_m4b(chapter_wavs, chapters, title, out_m4b)
    manifest["output"] = str(out_m4b)
    write_json_atomic(manifest_path, manifest)
    status["phase"] = "done"
    status["current"]["phase"] = "done"
    status["output"] = str(out_m4b)
    save_status()
    emit_event("run_completed", output=str(out_m4b))
    return out_m4b


def main() -> int:
    parser = argparse.ArgumentParser(description="Convert an EPUB into a local audiobook using Piper or Kokoro.")
    parser.add_argument("epub", type=Path, help="Input EPUB file")
    parser.add_argument("--outdir", type=Path, default=Path.cwd() / "audiobooks", help="Output directory")
    parser.add_argument("--tts-engine", choices=["piper", "kokoro"], default="kokoro", help="Text-to-speech backend")
    parser.add_argument("--mode", choices=["full", "rewrite-only", "tts-only", "hls-tts"], default="full", help="Pipeline mode. 'hls-tts' outputs HLS segments for live playback as chapters synthesize.")
    parser.add_argument("--chapters", default=None, help="Chapter selection like '5-12' or '1,3,8-10'")
    parser.add_argument("--rewrite-backend", choices=["openrouter", "local-7b"], default="local-7b", help="Narration rewrite backend")
    parser.add_argument("--rewrite-policy", choices=["full", "selective", "script-only"], default="full", help="Whether to rewrite every chunk, only flagged chunks, or skip LLM rewriting entirely")
    parser.add_argument("--rewrite-repo-id", default="Qwen/Qwen2.5-7B-Instruct-GGUF", help="Local rewrite model repo id")
    parser.add_argument("--rewrite-filename", default="*q2_k.gguf", help="Local rewrite GGUF filename glob")
    parser.add_argument("--rewrite-n-ctx", type=int, default=2048, help="Local rewrite context length")
    parser.add_argument("--rewrite-n-threads", type=int, default=4, help="Local rewrite thread count")
    parser.add_argument("--rewrite-n-batch", type=int, default=256, help="Local rewrite batch size")
    parser.add_argument("--voice-model", type=Path, default=Path(DEFAULT_VOICE_MODEL), help="Piper ONNX model path")
    parser.add_argument("--voice-config", type=Path, default=Path(DEFAULT_VOICE_CONFIG), help="Piper model config JSON")
    parser.add_argument("--piper-bin", default=str(Path.home() / "audiobook-tts-venv" / "bin" / "piper"), help="Piper executable")
    parser.add_argument("--kokoro-voice", default="af_heart", help="Kokoro voice id (for example: af_heart)")
    parser.add_argument("--kokoro-language", default=None, help="Kokoro language code (defaults from voice prefix)")
    parser.add_argument("--kokoro-repo-id", default="hexgrad/Kokoro-82M", help="Kokoro Hugging Face repo id")
    parser.add_argument("--kokoro-workers", type=int, default=2, help="Number of persistent Kokoro worker processes")
    parser.add_argument("--kokoro-speed", type=float, default=1.0, help="Kokoro speech speed")
    parser.add_argument("--max-chars", type=int, default=1200, help="Max characters per narration chunk")
    args = parser.parse_args()

    if not args.epub.exists():
        raise SystemExit(f"EPUB not found: {args.epub}")
    if args.mode != "rewrite-only" and args.tts_engine == "piper":
        if not args.voice_model.exists():
            raise SystemExit(f"Voice model not found: {args.voice_model}")
        if not args.voice_config.exists():
            raise SystemExit(f"Voice config not found: {args.voice_config}")
        if not Path(args.piper_bin).exists():
            raise SystemExit(f"Piper executable not found: {args.piper_bin}")

    args.outdir.mkdir(parents=True, exist_ok=True)
    out = process_book(
        epub_path=args.epub,
        outdir=args.outdir,
        tts_engine=args.tts_engine,
        rewrite_backend=args.rewrite_backend,
        rewrite_policy=args.rewrite_policy,
        rewrite_repo_id=args.rewrite_repo_id,
        rewrite_filename=args.rewrite_filename,
        rewrite_n_ctx=args.rewrite_n_ctx,
        rewrite_n_threads=args.rewrite_n_threads,
        rewrite_n_batch=args.rewrite_n_batch,
        piper_model=args.voice_model,
        piper_config=args.voice_config,
        piper_bin=args.piper_bin,
        kokoro_voice=args.kokoro_voice,
        kokoro_language=args.kokoro_language,
        kokoro_repo_id=args.kokoro_repo_id,
        kokoro_speed=args.kokoro_speed,
        max_chars=args.max_chars,
        kokoro_workers=args.kokoro_workers,
        mode=args.mode,
        chapter_selection=args.chapters,
    )
    log(f"\nDone: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
