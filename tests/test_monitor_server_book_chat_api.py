"""HTTP tests for monitor_server book-chat index/query endpoints."""

from __future__ import annotations

import json
import socket
import sys
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import monitor_server  # noqa: E402
from book_chat.embeddings import FakeHashEmbedder  # noqa: E402


def _pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    _, port = s.getsockname()
    s.close()
    return int(port)


class MonitorServerBookChatAPITests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()
        monitor_server.library_paths(self.root)[0].mkdir(parents=True, exist_ok=True)

        self._orig_embedder_factory = monitor_server.book_chat_embedder_factory
        monitor_server.book_chat_embedder_factory = lambda: FakeHashEmbedder(dimension=16)
        self.addCleanup(
            lambda: setattr(monitor_server, "book_chat_embedder_factory", self._orig_embedder_factory)
        )

        monitor_server.Handler.root = self.root
        self.addCleanup(lambda: setattr(monitor_server.Handler, "root", monitor_server.ROOT))

        self._host = "127.0.0.1"
        self._port = _pick_free_port()
        self._server = monitor_server.ThreadingHTTPServer((self._host, self._port), monitor_server.Handler)
        self._thread = threading.Thread(target=self._server.serve_forever, daemon=True)
        self._thread.start()
        self.addCleanup(self._shutdown_server)

    def _shutdown_server(self) -> None:
        self._server.shutdown()
        self._server.server_close()
        self._thread.join(timeout=5.0)

    def _url(self, path: str) -> str:
        return f"http://{self._host}:{self._port}{path}"

    def _post_json(self, path: str, body: dict) -> tuple[int, Any]:
        data = json.dumps(body).encode("utf-8")
        req = urllib.request.Request(
            self._url(path),
            data=data,
            method="POST",
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def test_book_chat_index_and_query(self) -> None:
        book_id = "test-book-001"
        st_idx, idx = self._post_json(
            "/api/library/book-chat/index",
            {
                "book_id": book_id,
                "passages": [
                    {"chapter": "Intro", "text": "Discipline is built in small steps."},
                    {"chapter": "Ch2", "text": "Rest helps the mind recover."},
                ],
            },
        )
        self.assertEqual(st_idx, 200)
        self.assertTrue(idx.get("ok"))
        self.assertEqual(idx.get("book_id"), book_id)
        self.assertEqual(idx.get("passage_count"), 2)

        st_q, q = self._post_json(
            "/api/library/book-chat/query",
            {"book_id": book_id, "question": "How is discipline built?", "top_k": 2},
        )
        self.assertEqual(st_q, 200)
        self.assertEqual(q.get("book_id"), book_id)
        self.assertIn("answer", q)
        self.assertGreaterEqual(len(q.get("citations") or []), 1)
        self.assertGreaterEqual(len(q.get("retrieved_passages") or []), 1)
        self.assertEqual(q.get("model_provider"), "retrieval_only")
        self.assertIn("model", q)
        self.assertIs(q.get("fallback_used"), False)

    def test_book_chat_query_missing_index_returns_404(self) -> None:
        st, body = self._post_json(
            "/api/library/book-chat/query",
            {"book_id": "no-such-index", "question": "hello"},
        )
        self.assertEqual(st, 404)
        self.assertIn("error", body)

    def test_book_chat_index_requires_book_id_and_passages(self) -> None:
        st, body = self._post_json("/api/library/book-chat/index", {})
        self.assertEqual(st, 400)
        self.assertIn("error", body)


if __name__ == "__main__":
    unittest.main()
