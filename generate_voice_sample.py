#!/usr/bin/env python3
"""Generate a short Kokoro voice sample WAV. Called by monitor_server.py."""
import argparse
import sys
from pathlib import Path

SAMPLE_TEXT = (
    "The sky above the port was the color of television, "
    "tuned to a dead channel. It's not like I'm using, "
    "Case heard someone say, as he shouldered his way "
    "through the crowd around the door of the Chat."
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--voice", required=True, help="Voice name, e.g. af_heart")
    parser.add_argument("--output", required=True, help="Output WAV path")
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--repo-id", default="hexgrad/Kokoro-82M")
    args = parser.parse_args()

    from kokoro import KPipeline
    import soundfile as sf
    import numpy as np

    voice = args.voice.strip()
    # Determine language code from voice: first letter
    lang_code = voice[0] if voice else 'a'

    pipeline = KPipeline(lang_code=lang_code, repo_id=args.repo_id)

    all_audio = []
    for _gs, _ps, audio in pipeline(
        SAMPLE_TEXT,
        voice=voice,
        speed=args.speed,
        split_pattern=r"\n+",
    ):
        all_audio.append(audio)

    if not all_audio:
        print("ERROR: no audio generated", file=sys.stderr)
        sys.exit(1)

    combined = np.concatenate(all_audio)
    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(out), combined, 24000)
    print(f"OK {out} ({len(combined)} samples, {len(combined)/24000:.1f}s)")


if __name__ == "__main__":
    main()
