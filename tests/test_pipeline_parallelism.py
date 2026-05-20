import sys
import threading
import time
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from epub_to_audiobook import (
    build_ffmetadata,
    build_tts_cache_payload,
    chunk_text,
    process_chunks_pipelined,
    tts_cache_matches,
    write_tts_cache,
    write_wav_from_float32,
    validate_rewrite_output,
)


class PipelineParallelismTests(unittest.TestCase):
    def test_overlap_rewrite_and_synth(self):
        events = []
        rewrite1_started = threading.Event()

        def rewrite_fn(item):
            events.append(f"rewrite-{item}")
            if item == 1:
                rewrite1_started.set()
            time.sleep(0.05)
            return f"rewritten-{item}"

        def synth_fn(item, text):
            events.append(f"synth-{item}")
            if item == 0:
                self.assertTrue(
                    rewrite1_started.wait(1.0),
                    "rewrite for the next chunk did not overlap with synth",
                )
            time.sleep(0.05)
            return f"wav-{item}"

        results = process_chunks_pipelined([0, 1, 2], rewrite_fn, synth_fn, max_buffer=1)

        self.assertEqual(results, ["wav-0", "wav-1", "wav-2"])
        self.assertEqual(events[0], "rewrite-0")
        self.assertIn("rewrite-1", events)

    def test_long_sentence_chunking_respects_max_chars_when_possible(self):
        text = " ".join([f"word{i}" for i in range(120)])
        chunks = chunk_text(text, max_chars=120)

        self.assertGreater(len(chunks), 1)
        self.assertTrue(all(len(chunk) <= 120 for chunk in chunks))

    def test_ffmetadata_escapes_special_values(self):
        chapter = type("ChapterLike", (), {"title": "A=B; C#D\nE"})()
        metadata = build_ffmetadata([chapter], [1.0], "Book=Title")

        self.assertIn("title=Book\\=Title", metadata)
        self.assertIn("title=A\\=B\\; C\\#D\\nE", metadata)

    def test_rewrite_validation_rejects_truncated_output(self):
        original = " ".join(["word"] * 80)
        ok, reason = validate_rewrite_output(original, "too short")

        self.assertFalse(ok)
        self.assertEqual(reason, "too_short")

    def test_tts_cache_requires_matching_payload(self):
        with TemporaryDirectory() as tmp:
            wav = Path(tmp) / "chunk.wav"
            write_wav_from_float32(wav, np.zeros(240, dtype=np.float32), sample_rate=24000)
            payload = build_tts_cache_payload(
                engine="kokoro",
                tts_text="hello",
                settings={"voice": "af_heart", "speed": 1.0},
            )
            write_tts_cache(wav, payload)

            self.assertTrue(tts_cache_matches(wav, payload))
            changed = build_tts_cache_payload(
                engine="kokoro",
                tts_text="hello again",
                settings={"voice": "af_heart", "speed": 1.0},
            )
            self.assertFalse(tts_cache_matches(wav, changed))


if __name__ == "__main__":
    unittest.main()
