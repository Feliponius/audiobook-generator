import sys
import threading
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from epub_to_audiobook import process_chunks_pipelined


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


if __name__ == "__main__":
    unittest.main()
