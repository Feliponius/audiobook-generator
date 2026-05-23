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
from tests.epub_fixtures import write_tiny_epub  # noqa: E402


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

    def _get_json(self, path: str) -> tuple[int, Any]:
        req = urllib.request.Request(self._url(path), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

    def _delete(self, path: str) -> tuple[int, Any]:
        req = urllib.request.Request(self._url(path), method="DELETE")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = resp.read().decode("utf-8")
                return resp.status, json.loads(body) if body.strip() else {}
        except urllib.error.HTTPError as e:
            raw = e.read().decode("utf-8")
            return e.code, json.loads(raw) if raw.strip() else {}

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
            {
                "book_id": book_id,
                "question": "How is discipline built?",
                "top_k": 2,
                "use_model": False,
            },
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

    def test_book_chat_memory_crud(self) -> None:
        book_id = "mem-book-001"
        st_get0, body0 = self._get_json(f"/api/library/book-chat/memory?book_id={book_id}")
        self.assertEqual(st_get0, 200)
        self.assertTrue(body0.get("ok"))
        self.assertEqual(body0.get("book_id"), book_id)
        self.assertEqual(body0.get("memories"), [])

        st_post, saved = self._post_json(
            "/api/library/book-chat/memory",
            {"book_id": book_id, "text": "Small habits matter.", "source": "insight"},
        )
        self.assertEqual(st_post, 200)
        self.assertTrue(saved.get("ok"))
        memory = saved.get("memory") or {}
        self.assertEqual(memory.get("book_id"), book_id)
        self.assertEqual(memory.get("text"), "Small habits matter.")
        self.assertEqual(memory.get("source"), "insight")
        memory_id = memory.get("memory_id")
        self.assertTrue(memory_id)

        st_get1, body1 = self._get_json(f"/api/library/book-chat/memory?book_id={book_id}")
        self.assertEqual(st_get1, 200)
        self.assertEqual(len(body1.get("memories") or []), 1)
        self.assertEqual(body1["memories"][0]["memory_id"], memory_id)

        st_del, del_body = self._delete(
            f"/api/library/book-chat/memory?book_id={book_id}&memory_id={memory_id}"
        )
        self.assertEqual(st_del, 200)
        self.assertTrue(del_body.get("deleted"))

        st_get2, body2 = self._get_json(f"/api/library/book-chat/memory?book_id={book_id}")
        self.assertEqual(body2.get("memories"), [])

    def test_book_chat_memory_post_with_metadata(self) -> None:
        book_id = "mem-meta-001"
        citations = [
            {
                "passage_id": "p1",
                "chapter": "Chapter 3",
                "snippet": "Lead with curiosity.",
            }
        ]
        st_post, saved = self._post_json(
            "/api/library/book-chat/memory",
            {
                "book_id": book_id,
                "text": "Full answer about influence.",
                "source": "insight",
                "title": "Influencing Difficult Coworkers",
                "question": "How do I influence lazy coworkers?",
                "action": "socratic",
                "citations": citations,
            },
        )
        self.assertEqual(st_post, 200)
        memory = saved.get("memory") or {}
        self.assertEqual(memory.get("title"), "Influencing Difficult Coworkers")
        self.assertEqual(memory.get("question"), "How do I influence lazy coworkers?")
        self.assertEqual(memory.get("action"), "socratic")
        self.assertEqual(memory.get("citations"), citations)

        st_get, body = self._get_json(f"/api/library/book-chat/memory?book_id={book_id}")
        self.assertEqual(len(body.get("memories") or []), 1)
        got = body["memories"][0]
        self.assertEqual(got.get("title"), "Influencing Difficult Coworkers")
        self.assertEqual(got.get("question"), "How do I influence lazy coworkers?")
        self.assertEqual(got.get("action"), "socratic")
        self.assertEqual(got.get("citations"), citations)

        st_min, saved_min = self._post_json(
            "/api/library/book-chat/memory",
            {"book_id": book_id, "text": "Minimal memory.", "source": "user"},
        )
        self.assertEqual(st_min, 200)
        minimal = saved_min.get("memory") or {}
        self.assertEqual(minimal.get("text"), "Minimal memory.")
        self.assertNotIn("title", minimal)

    def test_book_chat_memory_post_requires_fields(self) -> None:
        st, body = self._post_json("/api/library/book-chat/memory", {})
        self.assertEqual(st, 400)
        self.assertIn("error", body)

    def _seed_catalog_book_with_epub(self, book_id: str, epub_path: Path) -> None:
        rel = epub_path.relative_to(self.root).as_posix()
        catalog = {
            "version": 1,
            "books": [
                {
                    "id": book_id,
                    "title": "Auto Index Test",
                    "author": "Test",
                    "epub_rel_path": rel,
                }
            ],
        }
        monitor_server.write_catalog(self.root, catalog)

    def test_book_chat_auto_index_from_epub(self) -> None:
        book_id = "auto-index-epub-001"
        uploads = self.root / "library" / "uploads" / book_id
        uploads.mkdir(parents=True, exist_ok=True)
        epub_path = uploads / "book.epub"
        write_tiny_epub(
            epub_path,
            [
                (
                    "Chapter One",
                    "Discipline is built through small steps taken every day.",
                ),
            ],
        )
        self._seed_catalog_book_with_epub(book_id, epub_path)

        st0, status0 = self._get_json(f"/api/library/book-chat/index-status?book_id={book_id}")
        self.assertEqual(st0, 200)
        self.assertTrue(status0.get("ok"))
        self.assertFalse(status0.get("indexed"))
        self.assertEqual(status0.get("passage_count"), 0)

        st_idx, idx = self._post_json(
            "/api/library/book-chat/auto-index",
            {"book_id": book_id},
        )
        self.assertEqual(st_idx, 200)
        self.assertTrue(idx.get("ok"))
        self.assertEqual(idx.get("book_id"), book_id)
        self.assertGreater(idx.get("passage_count", 0), 0)
        self.assertIn(idx.get("status"), ("indexed", "already_indexed"))

        st1, status1 = self._get_json(f"/api/library/book-chat/index-status?book_id={book_id}")
        self.assertTrue(status1.get("indexed"))
        self.assertGreater(status1.get("passage_count", 0), 0)

        st_q, q = self._post_json(
            "/api/library/book-chat/query",
            {
                "book_id": book_id,
                "question": "How is discipline built?",
                "top_k": 2,
                "use_model": False,
            },
        )
        self.assertEqual(st_q, 200)
        self.assertGreaterEqual(len(q.get("citations") or []), 1)
        cite_text = " ".join(
            (c.get("snippet") or "") for c in (q.get("citations") or [])
        ).lower()
        self.assertTrue(
            "discipline" in cite_text or "small steps" in cite_text,
            msg=cite_text,
        )

    def test_book_chat_index_job_returns_quickly_and_completes(self) -> None:
        book_id = "index-job-epub-001"
        uploads = self.root / "library" / "uploads" / book_id
        uploads.mkdir(parents=True, exist_ok=True)
        epub_path = uploads / "book.epub"
        write_tiny_epub(
            epub_path,
            [("Chapter One", "Discipline grows through small daily steps.")],
        )
        self._seed_catalog_book_with_epub(book_id, epub_path)

        st_post, job = self._post_json(
            "/api/library/book-chat/index-job",
            {"book_id": book_id},
        )
        self.assertEqual(st_post, 200)
        self.assertTrue(job.get("ok"))
        self.assertEqual(job.get("book_id"), book_id)
        self.assertIn(job.get("status"), ("running", "done"))

        for _ in range(50):
            st_get, status = self._get_json(
                f"/api/library/book-chat/index-job-status?book_id={book_id}"
            )
            self.assertEqual(st_get, 200)
            if status.get("status") == "done" and status.get("percent") == 100:
                break
        else:
            self.fail(f"index job did not complete: {status}")

        self.assertGreater(status.get("passage_count", 0), 0)
        st_idx, idx = self._get_json(f"/api/library/book-chat/index-status?book_id={book_id}")
        self.assertTrue(idx.get("indexed"))
        self.assertEqual(st_idx, 200)

    def test_book_chat_index_job_duplicate_post_while_running(self) -> None:
        from book_chat.index_job import default_job_status, write_index_job

        book_id = "index-job-running-001"
        uploads = self.root / "library" / "uploads" / book_id
        uploads.mkdir(parents=True, exist_ok=True)
        epub_path = uploads / "book.epub"
        write_tiny_epub(epub_path, [("Ch1", "Some text for indexing.")])
        self._seed_catalog_book_with_epub(book_id, epub_path)

        running = default_job_status(self.root, book_id)
        running.update(
            {
                "status": "running",
                "stage": "embedding",
                "message": "Embedding passages 1 / 10",
                "current": 1,
                "total": 10,
                "percent": 10,
                "started_at": "2026-05-23T12:00:00+00:00",
                "updated_at": "2026-05-23T12:00:01+00:00",
            }
        )
        write_index_job(self.root, book_id, running)

        st_post, job = self._post_json(
            "/api/library/book-chat/index-job",
            {"book_id": book_id},
        )
        self.assertEqual(st_post, 200)
        self.assertEqual(job.get("status"), "running")
        self.assertEqual(job.get("started_at"), "2026-05-23T12:00:00+00:00")

    def test_book_chat_query_action_socratic_retrieval_only(self) -> None:
        book_id = "action-socratic-001"
        st_idx, _ = self._post_json(
            "/api/library/book-chat/index",
            {
                "book_id": book_id,
                "passages": [{"chapter": "Intro", "text": "Ask before advising."}],
            },
        )
        self.assertEqual(st_idx, 200)
        st_q, q = self._post_json(
            "/api/library/book-chat/query",
            {
                "book_id": book_id,
                "question": "coworkers",
                "action": "socratic",
                "use_model": False,
            },
        )
        self.assertEqual(st_q, 200)
        self.assertEqual(q.get("action"), "socratic")

    def test_book_chat_query_defaults_use_model_true(self) -> None:
        from book_chat.model_gateway import HermesGatewayResult

        book_id = "action-default-model-001"
        st_idx, _ = self._post_json(
            "/api/library/book-chat/index",
            {
                "book_id": book_id,
                "passages": [{"chapter": "Intro", "text": "Practice small steps daily."}],
            },
        )
        self.assertEqual(st_idx, 200)

        captured: dict = {}

        def fake_gateway(prompt, *, model="gpt-5.5", **kwargs):
            captured["model"] = model
            captured["prompt"] = prompt
            return HermesGatewayResult(
                ok=True,
                provider="hermes_openai_codex",
                model=model,
                text="GPT answer ready.",
            )

        import book_chat.service as book_chat_service

        orig = book_chat_service.ask_via_hermes_codex
        book_chat_service.ask_via_hermes_codex = fake_gateway
        try:
            st_q, q = self._post_json(
                "/api/library/book-chat/query",
                {"book_id": book_id, "question": "How to practice?", "action": "explain"},
            )
        finally:
            book_chat_service.ask_via_hermes_codex = orig

        self.assertEqual(st_q, 200)
        self.assertEqual(captured.get("model"), "gpt-5.5")
        self.assertEqual(q.get("action"), "explain")
        self.assertEqual(q.get("model_provider"), "hermes_openai_codex")
        self.assertFalse(q.get("fallback_used"))

    def test_book_chat_query_passes_custom_model(self) -> None:
        from book_chat.model_gateway import HermesGatewayResult

        book_id = "action-custom-model-001"
        self._post_json(
            "/api/library/book-chat/index",
            {
                "book_id": book_id,
                "passages": [{"chapter": "Intro", "text": "Lead with curiosity."}],
            },
        )

        captured: dict = {}

        def fake_gateway(prompt, *, model="gpt-5.5", **kwargs):
            captured["model"] = model
            return HermesGatewayResult(
                ok=True,
                provider="hermes_openai_codex",
                model=model,
                text="Custom model answer.",
            )

        import book_chat.service as book_chat_service

        orig = book_chat_service.ask_via_hermes_codex
        book_chat_service.ask_via_hermes_codex = fake_gateway
        try:
            st_q, q = self._post_json(
                "/api/library/book-chat/query",
                {
                    "book_id": book_id,
                    "question": "leadership",
                    "use_model": True,
                    "model": "gpt-5.5",
                },
            )
        finally:
            book_chat_service.ask_via_hermes_codex = orig

        self.assertEqual(st_q, 200)
        self.assertEqual(captured.get("model"), "gpt-5.5")
        self.assertEqual(q.get("model"), "gpt-5.5")


if __name__ == "__main__":
    unittest.main()
