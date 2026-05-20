# Audiobook Generator

A self-hosted EPUB-to-audiobook pipeline with a polished web UI. Upload EPUBs, read them in-browser, convert to audiobooks using local TTS (Kokoro), and listen with resume support — all on your own hardware.

![Screenshot placeholder](docs/screenshot.png)

## Features

- **📚 Library Management** — Upload and browse EPUBs with cover extraction
- **📖 In-Browser Reader** — Read EPUBs directly (powered by epub.js)
- **🔊 Audiobook Generation** — Convert books to speech using local Kokoro TTS
- **⏯️ Progressive Playback** — Start listening before generation completes (HLS streaming)
- **📍 Resume Support** — Reading and listening positions persist
- **🔖 Bookmarks & Notes** — Save bookmarks in both reading and listening modes
- **📱 Mobile-First** — Designed for Android/mobile usage
- **🔒 Privacy-First** — Single-user, no cloud, runs entirely local

## Quick Start

### Prerequisites

- Python 3.10+
- ffmpeg (for audio encoding)

```bash
# Ubuntu/Debian
sudo apt install ffmpeg python3-venv

# macOS
brew install ffmpeg

# Windows (via chocolatey)
choco install ffmpeg
```

### Installation

```bash
# Clone the repo
git clone https://github.com/YOUR_USERNAME/audiobook-generator.git
cd audiobook-generator

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Download Kokoro voice model (first run)
python -c "from kokoro import KModel; KModel()"
```

### Running

```bash
# Start the server
python monitor_server.py --host 0.0.0.0 --port 8123

# Or use the startup script
./start.sh
```

Then open `http://localhost:8123` in your browser.

## Usage

1. **Upload a book** — Click "Upload EPUB" on the library page
2. **Start conversion** — Open a book and click "Start audiobook"
3. **Read or listen** — Use the reader or wait for audio generation
4. **Progressive playback** — Start listening once the first chapter is ready

## Configuration

Settings are managed through the web UI at `/settings`:

- **Voice** — Choose Kokoro voice (af_heart, af_sky, am_michael, etc.)
- **Workers** — Number of parallel TTS processes (default: 2)
- **Rewrite Policy** — Text cleanup strategy:
  - `script-only` — Deterministic cleanup (default, fastest)
  - `selective` — LLM rewrite for complex passages only
  - `full` — LLM rewrite for all passages (slowest, best quality)

## Architecture

```
┌─────────────┐     ┌─────────────────┐     ┌─────────────┐
│   Web UI    │────▶│  monitor_server │────▶│   Library   │
│ (dashboard) │     │   (Python HTTP) │     │  (SQLite)   │
└─────────────┘     └─────────────────┘     └─────────────┘
                            │
                            ▼
                     ┌─────────────────┐
                     │ epub_to_audiobook│
                     │    (pipeline)    │
                     └─────────────────┘
                            │
                    ┌───────┴───────┐
                    ▼               ▼
              ┌─────────┐     ┌──────────┐
              │  Kokoro │     │  ffmpeg  │
              │   TTS   │     │ (encode) │
              └─────────┘     └──────────┘
```

## File Structure

```
.
├── monitor_server.py      # Web server & API
├── epub_to_audiobook.py   # Conversion pipeline
├── dashboard/             # Web UI (single-page app)
│   └── index.html
├── docs/                  # Documentation
├── tests/                 # Test suite
├── requirements.txt       # Python dependencies
└── README.md             # This file
```

## Advanced Usage

### Command Line

```bash
# Convert an EPUB directly (no web UI)
python epub_to_audiobook.py book.epub \
    --outdir ./output \
    --tts-engine kokoro \
    --kokoro-voice af_heart \
    --kokoro-workers 2 \
    --rewrite-policy script-only
```

LLM rewriting is opt-in from the CLI. Use `--rewrite-policy selective` or
`--rewrite-policy full` only after installing and configuring the matching
rewrite backend.

### Chunking

Text is split into chunks for TTS:
- **Default chunk size:** 1,200 characters
- **Soft limit:** ~600 characters (target size)
- Chunks are split at paragraph/sentence boundaries

### Output Formats

- **M4A/AAC** — Primary listening format (128kbps)
- **HLS** — ADTS AAC segments for live streaming during generation
- **WAV** — Intermediate format (cleaned up automatically)

## Deployment

### Tailscale (Recommended)

The app is designed for tailnet/private network access:

```bash
# On your server
tailscale up
python monitor_server.py --host 0.0.0.0 --port 8123

# Access via your tailnet
# http://your-machine:8123
```

### Docker (Optional)

```bash
# Build
docker build -t audiobook-generator .

# Run
docker run -p 8123:8123 \
  -v $(pwd)/library:/app/library \
  audiobook-generator
```

## Troubleshooting

**Generation seems stuck**
- Check the process: `ps aux | grep epub_to_audiobook`
- Check logs in `library/runs/<id>/events.jsonl`

**No audio playback**
- Ensure ffmpeg is installed: `ffmpeg -version`
- Check browser console for HLS errors

**Out of memory**
- Reduce Kokoro workers: `--kokoro-workers 1`
- Reduce chunk size: `--max-chars 800`

## License

MIT License — See [LICENSE](LICENSE) file.

## Credits

- [Kokoro](https://github.com/hexgrad/kokoro) — Fast, local TTS
- [epub.js](https://github.com/futurepress/epub.js) — In-browser EPUB reader
- [ebooklib](https://github.com/aerkalov/ebooklib) — EPUB parsing
