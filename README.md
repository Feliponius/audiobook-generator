# Audiobook Generator

Self-hosted EPUB-to-audiobook pipeline with local TTS, book chat, and live HLS streaming.

## Features

### Core Pipeline
- **Dual TTS Engines** — Kokoro (default, GPU-accelerated) or Piper (CPU fallback)
- **Smart TTS Caching** — Fingerprint-based cache: model changes, voice swaps, text edits all trigger selective regeneration. No full re-synthesis on small changes.
- **HLS Live Streaming** — ADTS AAC segments stream to browser as chapters synthesize. Dynamic TARGETDURATION.
- **Chapter Resume** — Detects fully-generated chapters and skips them on re-run.
- **Intermediate Cleanup** — Automatically deletes chunk/chapter WAVs after final M4B is ready (configurable via `--output-retention`).
- **LLM Rewrite Validation** — Rejects truncated or garbled rewrite output; falls back to original text gracefully.
- **EPUB TOC Title Mapping** — Shows real chapter names from EPUB navigation instead of packaging filenames.
- **Metadata Escaping** — Safe handling of special characters in chapter titles for ffmetadata.

### Book Chat
- **Ask Questions** — Query any book's content with natural language
- **Citation Links** — Answers include source citations to the exact passage
- **Multiple Answer Modes** — Including GPT-5.5 via Hermes Codex gateway
- **Auto-Indexing** — Books are indexed automatically on upload
- **Memory API** — Save and retrieve insights across sessions

### Web Dashboard
- **Live HLS Player** — Browse and listen to books as they generate
- **Voice Preview** — Browse all 80+ Kokoro voices, listen to samples
- **Settings Page** — Configure defaults (engine, voice, speed, rewrite policy)
- **Service Worker** — Offline audio caching for the live player
- **Home Screen** — PWA installable with app icon
- **Tailscale HTTPS** — Secure remote access via Tailscale proxy

## Quick Start

### Requirements
- Python 3.10+
- ffmpeg
- Kokoro (recommended) or Piper TTS

### Install

```bash
git clone https://github.com/Feliponius/audiobook-generator.git
cd audiobook-generator
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### Generate an Audiobook

```bash
# Default (Kokoro, no LLM rewrite)
python epub_to_audiobook.py book.epub --outdir ./out

# Piper (CPU-friendly)
python epub_to_audiobook.py book.epub --tts-engine piper \
  --piper-model ~/voices/en_US-lessac-medium.onnx \
  --piper-config ~/voices/en_US-lessac-medium.onnx.json \
  --outdir ./out

# With LLM rewriting (opt-in)
python epub_to_audiobook.py book.epub \
  --rewrite-policy selective \
  --rewrite-backend openrouter \
  --outdir ./out

# Live HLS streaming mode
python epub_to_audiobook.py book.epub \
  --mode hls-tts \
  --outdir ./out
```

### Run the Dashboard Server

```bash
python monitor_server.py --host 127.0.0.1 --port 8002
```

Then open `http://127.0.0.1:8002` in your browser.

## CLI Reference

| Argument | Default | Description |
|---|---|---|
| `--tts-engine` | `kokoro` | TTS engine: `kokoro` or `piper` |
| `--kokoro-voice` | `af_heart` | Kokoro voice (e.g. `af_heart`, `am_liam`, `bf_emma`) |
| `--kokoro-speed` | `1.0` | Kokoro playback speed |
| `--kokoro-repo-id` | `hexgrad/Kokoro-82M` | Kokoro model repo |
| `--kokoro-workers` | `2` | Parallel Kokoro workers |
| `--mode` | `full` | Pipeline mode: `full`, `rewrite-only`, `tts-only`, `hls-tts` |
| `--rewrite-policy` | `script-only` | LLM rewrite: `full`, `selective`, `script-only` |
| `--rewrite-backend` | `local-7b` | Rewrite backend: `openrouter` or `local-7b` |
| `--output-retention` | `delete_intermediates_after_complete` | Cleanup: `keep_all` or `delete_intermediates_after_complete` |
| `--max-chars` | `650` | Max characters per TTS chunk |
| `--chapters` | all | Chapter selection: `5-12` or `1,3,8-10` |
| `--outdir` | `./out` | Output directory |

## Project Structure

```
audiobook-generator/
├── epub_to_audiobook.py       # Core pipeline script
├── monitor_server.py          # HTTP dashboard server
├── tts_cache.py               # TTS caching & HLS AAC utilities
├── generate_voice_sample.py   # Voice preview generator
├── dashboard/                 # Web UI (index.html, sw.js, assets)
│   ├── index.html             # Main dashboard page
│   ├── sw.js                  # Service worker for offline caching
│   ├── tailscale_proxy.py     # Tailscale HTTPS proxy
│   └── assets/                # Icons, CSS, JS
├── book_chat/                 # Book Q&A backend
│   ├── service.py             # API surface
│   ├── embeddings.py          # LocalBGE embedder
│   ├── index_job.py           # Background indexing
│   └── memory_store.py        # Insight persistence
└── tests/                     # Test suite
```

## Output Formats

- **M4B** — Final audiobook with chapter markers
- **M4A/AAC** — Per-chapter audio files
- **HLS** — ADTS AAC segments for live streaming during generation
- **WAV** — Intermediate format (cleaned up automatically)

## Caching

The TTS cache (`tts_cache.py`) stores fingerprint-based payloads alongside each generated WAV. A chunk is reused only if:

1. The WAV file is valid and non-empty
2. The engine (Kokoro/Piper) matches
3. The TTS text is identical (via SHA256)
4. All settings (voice, speed, model files) are identical

This means changing a voice, updating a model file, or fixing a typo will only regenerate affected chunks.

## License

MIT
