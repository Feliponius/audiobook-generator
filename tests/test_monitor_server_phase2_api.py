"""Headless HTTP tests for monitor_server phase-2 library/settings APIs.

Uses a temporary workspace root (no real library/), a stub epub_to_audiobook.py,
and a patched subprocess.Popen so conversion start is verified without running
the full pipeline.
"""
from __future__ import annotations

import json
import os
import socket
import sys
import threading
import time
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from urllib.parse import urlencode, quote

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

import monitor_server  # noqa: E402


def _pick_free_port() -> int:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.bind(("127.0.0.1", 0))
    _, port = s.getsockname()
    s.close()
    return int(port)


def _multipart_epub_upload(epub_bytes: bytes, boundary: str = "----Phase2TestBoundary") -> tuple[bytes, str]:
    crlf = b"\r\n"
    parts: list[bytes] = [
        f"--{boundary}".encode(),
        b'Content-Disposition: form-data; name="file"; filename="sample.epub"',
        b"Content-Type: application/epub+zip",
        b"",
        epub_bytes,
        f"--{boundary}--".encode(),
    ]
    body = crlf.join(parts) + crlf
    ctype = f"multipart/form-data; boundary={boundary}"
    return body, ctype


class MonitorServerPhase2APITests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.root = Path(self._tmp.name).resolve()

        lib, uploads, covers, runs = monitor_server.library_paths(self.root)
        lib.mkdir(parents=True, exist_ok=True)
        uploads.mkdir(parents=True, exist_ok=True)
        covers.mkdir(parents=True, exist_ok=True)
        runs.mkdir(parents=True, exist_ok=True)

        stub = self.root / "epub_to_audiobook.py"
        stub.write_text(
            "#!/usr/bin/env python3\n"
            "import sys\n"
            'if __name__ == "__main__":\n'
            "    sys.exit(0)\n",
            encoding="utf-8",
        )

        self._popen_calls: list[dict[str, Any]] = []
        self._orig_popen = monitor_server.subprocess.Popen

        def _fake_popen(*args: Any, **kwargs: Any) -> object:
            self._popen_calls.append({"args": args, "kwargs": kwargs})

            class _P:
                pass

            return _P()

        monitor_server.subprocess.Popen = _fake_popen  # type: ignore[assignment]
        self.addCleanup(lambda: setattr(monitor_server.subprocess, "Popen", self._orig_popen))

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

    def _url(self, path: str, query: dict[str, str] | None = None) -> str:
        q = f"?{urlencode(query)}" if query else ""
        return f"http://{self._host}:{self._port}{path}{q}"

    def _get_json(self, path: str, query: dict[str, str] | None = None) -> tuple[int, Any]:
        req = urllib.request.Request(self._url(path, query), method="GET")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode("utf-8"))

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

    def _upload_epub(self, epub_bytes: bytes) -> tuple[int, Any]:
        body, ctype = _multipart_epub_upload(epub_bytes)
        req = urllib.request.Request(
            self._url("/api/library/upload"),
            data=body,
            method="POST",
            headers={"Content-Type": ctype},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))

    def _request(self, req: urllib.request.Request) -> tuple[int, bytes, dict[str, str]]:
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                return resp.status, resp.read(), dict(resp.headers.items())
        except urllib.error.HTTPError as e:
            return e.code, e.read(), dict(e.headers.items())

    def test_settings_get_default_shape(self) -> None:
        status, data = self._get_json("/api/settings")
        self.assertEqual(status, 200)
        st = data["settings"]
        self.assertIsInstance(st, dict)
        for key in (
            "version",
            "kokoro_voice",
            "kokoro_workers",
            "rewrite_policy",
            "hls_live",
            "output_retention",
        ):
            self.assertIn(key, st)
        self.assertIsInstance(st["version"], int)
        self.assertIsInstance(st["kokoro_voice"], str)
        self.assertIsInstance(st["kokoro_workers"], int)
        self.assertEqual(st["rewrite_policy"], "script-only")
        self.assertIsInstance(st["hls_live"], bool)
        self.assertIn(st["output_retention"], ("keep_all", "delete_intermediates_after_complete"))

    def test_settings_post_persistence_and_validation(self) -> None:
        s1, d1 = self._post_json(
            "/api/settings",
            {
                "kokoro_voice": "  bm_fable ",
                "kokoro_workers": 99,
                "rewrite_policy": "full",
                "hls_live": False,
                "output_retention": "delete_intermediates_after_complete",
                "ignored_field": "should_not_persist",
            },
        )
        self.assertEqual(s1, 200)
        merged = d1["settings"]
        self.assertEqual(merged["kokoro_voice"], "bm_fable")
        self.assertEqual(merged["kokoro_workers"], 2)
        self.assertEqual(merged["rewrite_policy"], "full")
        self.assertTrue(merged["hls_live"])
        self.assertEqual(merged["output_retention"], "delete_intermediates_after_complete")
        self.assertNotIn("ignored_field", merged)

        path = monitor_server.settings_path(self.root)
        self.assertTrue(path.is_file())
        disk = json.loads(path.read_text(encoding="utf-8"))
        self.assertEqual(disk["kokoro_voice"], "bm_fable")
        self.assertEqual(disk["kokoro_workers"], 2)
        self.assertEqual(disk["rewrite_policy"], "full")

        s2, d2 = self._post_json("/api/settings", {"kokoro_workers": 0, "rewrite_policy": "not-valid"})
        self.assertEqual(s2, 200)
        m2 = d2["settings"]
        self.assertEqual(m2["kokoro_workers"], 2)
        self.assertEqual(m2["rewrite_policy"], "script-only")

    def test_epub_upload_library_and_patch_progress_bookmarks_notes(self) -> None:
        up_status, up = self._upload_epub(b"fake-epub-bytes")
        self.assertEqual(up_status, 200)
        book = up["book"]
        book_id = book["id"]
        self.assertTrue(book.get("epub_rel_path"))
        self.assertEqual(book.get("reading_bookmarks"), [])
        self.assertEqual(book.get("listening_bookmarks"), [])
        self.assertEqual(book.get("notes"), [])

        st_lib, lib = self._get_json("/api/library")
        self.assertEqual(st_lib, 200)
        self.assertEqual(len(lib["books"]), 1)
        self.assertEqual(lib["books"][0]["id"], book_id)

        p1, d1 = self._post_json(
            "/api/library/patch",
            {
                "id": book_id,
                "read_cfi": "epubcfi(/6/4[chap]!/4/2/1:0)",
                "read_progress_hint": "42%",
                "listen_time_s": 12.5,
                "listen_chapter_index": 3,
                "listen_progress_hint": "near end",
                "listen_src": "hls",
                "listen_duration_s": 3600.0,
            },
        )
        self.assertEqual(p1, 200)
        b1 = d1["book"]
        self.assertEqual(b1["read_cfi"], "epubcfi(/6/4[chap]!/4/2/1:0)")
        self.assertEqual(b1["read_progress_hint"], "42%")
        self.assertEqual(b1["listen_time_s"], 12.5)
        self.assertEqual(b1["listen_chapter_index"], 3)
        self.assertEqual(b1["listen_progress_hint"], "near end")
        self.assertEqual(b1["listen_src"], "hls")
        self.assertEqual(b1["listen_duration_s"], 3600.0)
        self.assertIsNotNone(b1.get("read_updated_at"))
        self.assertIsNotNone(b1.get("listen_updated_at"))

        p2, d2 = self._post_json(
            "/api/library/patch",
            {
                "id": book_id,
                "add_reading_bookmark": {"cfi": "epubcfi(/1/2)", "label": "  mark-a  "},
                "add_listening_bookmark": {"chapter_index": 1, "time_s": 2.5, "label": "lb"},
            },
        )
        self.assertEqual(p2, 200)
        rb = d2["book"]["reading_bookmarks"]
        lb = d2["book"]["listening_bookmarks"]
        self.assertEqual(len(rb), 1)
        self.assertEqual(len(lb), 1)
        self.assertEqual(rb[0]["cfi"], "epubcfi(/1/2)")
        self.assertEqual(rb[0]["label"], "mark-a")
        rid = rb[0]["id"]
        lid = lb[0]["id"]

        p3, d3 = self._post_json(
            "/api/library/patch",
            {
                "id": book_id,
                "remove_reading_bookmark_id": rid,
                "remove_listening_bookmark_id": lid,
            },
        )
        self.assertEqual(p3, 200)
        self.assertEqual(d3["book"]["reading_bookmarks"], [])
        self.assertEqual(d3["book"]["listening_bookmarks"], [])

    def test_media_head_and_range_requests_for_audio(self) -> None:
        media_dir = self.root / "media"
        media_dir.mkdir(parents=True, exist_ok=True)
        media_path = media_dir / "chapter.m4a"
        payload = b"0123456789abcdef"
        media_path.write_bytes(payload)
        aac_path = media_dir / "chunk-001.aac"
        aac_path.write_bytes(b"aac")
        rel = quote(str(media_path.relative_to(self.root)))
        aac_rel = quote(str(aac_path.relative_to(self.root)))

        head_req = urllib.request.Request(self._url("/media", {"path": rel}), method="HEAD")
        head_status, head_body, head_headers = self._request(head_req)
        self.assertEqual(head_status, 200)
        self.assertEqual(head_body, b"")
        self.assertEqual(head_headers.get("Content-Length"), str(len(payload)))
        self.assertEqual(head_headers.get("Content-Type"), "audio/mp4")
        self.assertEqual(head_headers.get("Accept-Ranges"), "bytes")

        aac_head_req = urllib.request.Request(self._url("/media", {"path": aac_rel}), method="HEAD")
        aac_head_status, _, aac_head_headers = self._request(aac_head_req)
        self.assertEqual(aac_head_status, 200)
        self.assertEqual(aac_head_headers.get("Content-Type"), "audio/aac")

        range_req = urllib.request.Request(
            self._url("/media", {"path": rel}),
            headers={"Range": "bytes=4-7"},
            method="GET",
        )
        range_status, range_body, range_headers = self._request(range_req)
        self.assertEqual(range_status, 206)
        self.assertEqual(range_body, payload[4:8])
        self.assertEqual(range_headers.get("Content-Range"), f"bytes 4-7/{len(payload)}")
        self.assertEqual(range_headers.get("Content-Length"), "4")
        self.assertEqual(range_headers.get("Accept-Ranges"), "bytes")

        bad_range_req = urllib.request.Request(
            self._url("/media", {"path": rel}),
            headers={"Range": f"bytes={len(payload)}-{len(payload) + 5}"},
            method="GET",
        )
        bad_status, _, bad_headers = self._request(bad_range_req)
        self.assertEqual(bad_status, 416)
        self.assertEqual(bad_headers.get("Content-Range"), f"bytes */{len(payload)}")

    def test_library_notes_are_added_updated_removed_and_persisted(self) -> None:
        up_status, up = self._upload_epub(b"fake-epub-bytes")
        self.assertEqual(up_status, 200)
        book_id = up["book"]["id"]

        p4, d4 = self._post_json(
            "/api/library/patch",
            {"id": book_id, "add_note": {"text": "  first note  "}},
        )
        self.assertEqual(p4, 200)
        notes = d4["book"]["notes"]
        self.assertEqual(len(notes), 1)
        nid = notes[0]["id"]
        self.assertEqual(notes[0]["text"], "first note")

        p5, d5 = self._post_json(
            "/api/library/patch",
            {"id": book_id, "update_note": {"id": nid, "text": "revised"}},
        )
        self.assertEqual(p5, 200)
        self.assertEqual(d5["book"]["notes"][0]["text"], "revised")

        p6, d6 = self._post_json("/api/library/patch", {"id": book_id, "remove_note_id": nid})
        self.assertEqual(p6, 200)
        self.assertEqual(d6["book"]["notes"], [])

        cat = monitor_server.read_catalog(self.root)
        persisted = next(x for x in cat["books"] if x["id"] == book_id)
        self.assertEqual(persisted["notes"], [])

    def test_media_m3u8_head_rewrites_playlist_urls(self) -> None:
        chapter_dir = self.root / "runs" / "book-a" / "chapters" / "001"
        chapter_dir.mkdir(parents=True, exist_ok=True)
        seg = chapter_dir / "chunk-0001.ts"
        seg.write_bytes(b"segment-bytes")
        playlist = chapter_dir / "chapter-001.m3u8"
        playlist.write_text("#EXTM3U\n#EXTINF:1.0,\nchunk-0001.ts\n", encoding="utf-8")
        rel = quote(str(playlist.relative_to(self.root)).replace(os.sep, "/"))

        head_req = urllib.request.Request(self._url(f"/media?path={rel}"), method="HEAD")
        head_status, head_body, head_headers = self._request(head_req)
        self.assertEqual(head_status, 200)
        self.assertEqual(head_body, b"")
        self.assertEqual(head_headers.get("Content-Type"), "application/vnd.apple.mpegurl")

        get_req = urllib.request.Request(self._url(f"/media?path={rel}"), method="GET")
        get_status, get_body, get_headers = self._request(get_req)
        self.assertEqual(get_status, 200)
        self.assertEqual(get_headers.get("Content-Type"), "application/vnd.apple.mpegurl")
        text = get_body.decode("utf-8")
        self.assertIn("/media?path=runs/book-a/chapters/001/chunk-0001.ts", text)

    def test_library_book_run_exposes_chapter_timeline_offsets(self) -> None:
        _, up = self._upload_epub(b"timeline-epub")
        book = up["book"]
        book_id = book["id"]
        slug = monitor_server.slugify_title(book["title"])
        rel = (Path("library/runs") / book_id / slug).as_posix()
        run_dir = self.root / rel
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "status.json").write_text(
            json.dumps(
                {
                    "phase": "done",
                    "title": book.get("title") or "t",
                    "chapters": [
                        {"index": 1, "title": "Intro", "status": "completed"},
                        {"index": 2, "title": "Chapter One", "status": "completed"},
                        {"index": 3, "title": "Chapter Two", "status": "running"},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "manifest.json").write_text(
            json.dumps(
                {
                    "output": str((run_dir / "book.m4b").resolve()),
                    "chapters": [
                        {"index": 1, "duration_s": 12.5},
                        {"index": 2, "duration_s": 30.0},
                        {"index": 3, "duration_s": 7.25},
                    ],
                }
            ),
            encoding="utf-8",
        )
        (run_dir / "book.m4b").write_bytes(b"m4b")
        cat = monitor_server.read_catalog(self.root)
        for row in cat.get("books", []):
            if row.get("id") == book_id:
                row["run_relpath"] = rel
                break
        monitor_server.write_catalog(self.root, cat)

        st_book, data_book = self._get_json("/api/library/book", {"id": book_id, "include_run": "1"})
        self.assertEqual(st_book, 200)
        chapters = data_book["book"]["run"]["chapters"]
        self.assertEqual(chapters[0]["start_s"], 0.0)
        self.assertEqual(chapters[0]["end_s"], 12.5)
        self.assertEqual(chapters[1]["start_s"], 12.5)
        self.assertEqual(chapters[1]["end_s"], 42.5)
        self.assertEqual(chapters[2]["start_s"], 42.5)
        self.assertEqual(chapters[2]["end_s"], 49.75)

    def test_library_patch_listen_absolute_transport_and_timeline_version(self) -> None:
        _, up = self._upload_epub(b"abs-listen-epub")
        book_id = up["book"]["id"]
        st, data = self._post_json(
            "/api/library/patch",
            {
                "id": book_id,
                "listen_abs_time_s": 125.5,
                "listen_chapter_time_s": 13.0,
                "listen_chapter_index": 2,
                "listen_transport": "book",
                "listen_timeline_version": 1,
                "listen_src": "final",
                "listen_time_s": 13.0,
            },
        )
        self.assertEqual(st, 200)
        b = data["book"]
        self.assertEqual(b["listen_abs_time_s"], 125.5)
        self.assertEqual(b["listen_chapter_time_s"], 13.0)
        self.assertEqual(b["listen_chapter_index"], 2)
        self.assertEqual(b["listen_transport"], "book")
        self.assertEqual(b["listen_timeline_version"], 1)
        cat = monitor_server.read_catalog(self.root)
        row = next(x for x in cat["books"] if x["id"] == book_id)
        self.assertEqual(row.get("listen_abs_time_s"), 125.5)
        self.assertEqual(row.get("listen_transport"), "book")

    def test_listening_bookmark_absolute_fields_and_legacy_time_s(self) -> None:
        _, up = self._upload_epub(b"bm-abs-epub")
        book_id = up["book"]["id"]
        st1, d1 = self._post_json(
            "/api/library/patch",
            {
                "id": book_id,
                "add_listening_bookmark": {
                    "chapter_index": 1,
                    "time_s": 2.5,
                    "label": "legacy-style",
                },
            },
        )
        self.assertEqual(st1, 200)
        lb = d1["book"]["listening_bookmarks"]
        self.assertEqual(len(lb), 1)
        self.assertEqual(lb[0]["chapter_index"], 1)
        self.assertEqual(lb[0]["time_s"], 2.5)
        self.assertEqual(lb[0]["chapter_time_s"], 2.5)
        self.assertIsNone(lb[0].get("abs_time_s"))

        st2, d2 = self._post_json(
            "/api/library/patch",
            {
                "id": book_id,
                "add_listening_bookmark": {
                    "chapter_index": 3,
                    "chapter_time_s": 1.0,
                    "abs_time_s": 99.25,
                    "timeline_version": 1,
                    "label": "abs-style",
                },
            },
        )
        self.assertEqual(st2, 200)
        lb2 = d2["book"]["listening_bookmarks"]
        self.assertEqual(len(lb2), 2)
        self.assertEqual(lb2[1]["abs_time_s"], 99.25)
        self.assertEqual(lb2[1]["chapter_time_s"], 1.0)
        self.assertEqual(lb2[1]["timeline_version"], 1)

    def test_library_start_uses_fixed_safe_runtime_settings(self) -> None:
        self._post_json(
            "/api/settings",
            {
                "kokoro_voice": "af_sarah",
                "kokoro_workers": 5,
                "rewrite_policy": "script-only",
                "hls_live": False,
            },
        )
        _, up = self._upload_epub(b"epub-for-start")
        book_id = up["book"]["id"]

        st, data = self._post_json("/api/library/start", {"id": book_id})
        self.assertEqual(st, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(self._popen_calls), 1)
        pop_kw = self._popen_calls[0]["kwargs"]
        self.assertIn("env", pop_kw)
        self.assertEqual(pop_kw["env"].get("VIRTUAL_ENV"), os.environ.get("VIRTUAL_ENV"))
        cmd = list(self._popen_calls[0]["args"][0])
        self.assertEqual(cmd[0], sys.executable)
        self.assertIn("--mode", cmd)
        self.assertEqual(cmd[cmd.index("--mode") + 1], "hls-tts")
        self.assertIn("--kokoro-voice", cmd)
        self.assertEqual(cmd[cmd.index("--kokoro-voice") + 1], "af_sarah")
        self.assertIn("--kokoro-workers", cmd)
        self.assertEqual(cmd[cmd.index("--kokoro-workers") + 1], "2")
        self.assertIn("--rewrite-policy", cmd)
        self.assertEqual(cmd[cmd.index("--rewrite-policy") + 1], "script-only")

        log_path = self.root / "library" / "runs" / book_id / "conversion.log"
        self.assertTrue(log_path.is_file())
        first_line = log_path.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(first_line.startswith("[launch] python="))
        self.assertIn(sys.executable, first_line)

        st2, data2 = self._post_json("/api/library/start", {"id": book_id})
        self.assertEqual(st2, 409)
        self.assertEqual(data2.get("error"), "conversion already in progress")

    def test_library_book_without_live_process_reports_stopped_not_running(self) -> None:
        orig_parse = monitor_server.parse_processes

        def _no_pipeline_processes() -> list[dict]:
            return []

        monitor_server.parse_processes = _no_pipeline_processes  # type: ignore[assignment]
        self.addCleanup(lambda: setattr(monitor_server, "parse_processes", orig_parse))

        _, up = self._upload_epub(b"epub-for-stopped-state")
        book = up["book"]
        book_id = book["id"]
        slug = monitor_server.slugify_title(book["title"])
        rel = (Path("library/runs") / book_id / slug).as_posix()
        run_dir = self.root / rel
        run_dir.mkdir(parents=True, exist_ok=True)
        (run_dir / "status.json").write_text(
            json.dumps({"phase": "tts", "title": book.get("title") or "t", "updated_at": "2026-01-01T00:00:00Z"}),
            encoding="utf-8",
        )
        (run_dir / "events.jsonl").write_text(
            json.dumps({"event": "chunk_tts_completed", "ts": "2026-01-01T00:00:00Z"}) + "\n",
            encoding="utf-8",
        )
        cat = monitor_server.read_catalog(self.root)
        for row in cat.get("books", []):
            if row.get("id") == book_id:
                row["run_relpath"] = rel
                break
        monitor_server.write_catalog(self.root, cat)

        st_book, data_book = self._get_json("/api/library/book", {"id": book_id, "include_run": "1"})
        self.assertEqual(st_book, 200)
        pub = data_book["book"]
        self.assertEqual(pub.get("conversion_status"), "stopped")
        self.assertFalse(pub.get("generation_is_live"))
        self.assertIsNotNone(pub.get("generation_last_event"))

    def test_stale_library_run_allows_restart(self) -> None:
        orig_parse = monitor_server.parse_processes

        def _no_pipeline_processes() -> list[dict]:
            return []

        monitor_server.parse_processes = _no_pipeline_processes  # type: ignore[assignment]
        self.addCleanup(lambda: setattr(monitor_server, "parse_processes", orig_parse))

        _, up = self._upload_epub(b"stale-run-epub")
        book = up["book"]
        book_id = book["id"]
        slug = monitor_server.slugify_title(book["title"])
        rel = (Path("library/runs") / book_id / slug).as_posix()
        run_dir = self.root / rel
        run_dir.mkdir(parents=True, exist_ok=True)
        outdir = self.root / "library" / "runs" / book_id
        outdir.mkdir(parents=True, exist_ok=True)
        (run_dir / "status.json").write_text(
            json.dumps({"phase": "rewriting", "title": book.get("title") or "t"}),
            encoding="utf-8",
        )
        (run_dir / "events.jsonl").write_text(
            json.dumps({"event": "chunk_start", "ts": "2026-01-01T00:00:00Z"}) + "\n",
            encoding="utf-8",
        )
        old = time.time() - 400
        os.utime(run_dir / "status.json", (old, old))
        os.utime(run_dir / "events.jsonl", (old, old))
        os.utime(run_dir, (old, old))

        cat = monitor_server.read_catalog(self.root)
        for row in cat.get("books", []):
            if row.get("id") == book_id:
                row["run_relpath"] = rel
                break
        monitor_server.write_catalog(self.root, cat)

        st, data = self._get_json("/api/library/book", {"id": book_id, "include_run": "1"})
        self.assertEqual(st, 200)
        pub = data["book"]
        self.assertEqual(pub.get("conversion_status"), "stalled")
        self.assertFalse(pub.get("generation_is_live"))
        self.assertIsNotNone(pub.get("generation_last_event"))

        st_start, start_data = self._post_json("/api/library/start", {"id": book_id})
        self.assertEqual(st_start, 200, msg=str(start_data))
        self.assertTrue(start_data.get("ok"))

    def test_resolve_library_pipeline_python_prefers_venv(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            self.assertEqual(monitor_server.resolve_library_pipeline_python(root), sys.executable)
            vpy = root / "venv" / "bin" / "python"
            vpy.parent.mkdir(parents=True, exist_ok=True)
            vpy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            vpy.chmod(0o755)
            self.assertEqual(monitor_server.resolve_library_pipeline_python(root), str(vpy))

    def test_resolve_library_pipeline_python_preserves_venv_wrapper_path_when_symlinked(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            bindir = root / "venv" / "bin"
            bindir.mkdir(parents=True, exist_ok=True)
            real = bindir / "python-real"
            real.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            real.chmod(0o755)
            vpy = bindir / "python"
            vpy.symlink_to(real)
            self.assertEqual(monitor_server.resolve_library_pipeline_python(root), str(vpy))

    def test_library_conversion_subprocess_env_without_venv_is_os_environ_copy(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            env = monitor_server.library_conversion_subprocess_env(root)
            self.assertEqual(env.get("HOME"), os.environ.get("HOME"))
            self.assertEqual(env.get("VIRTUAL_ENV"), os.environ.get("VIRTUAL_ENV"))

    def test_library_conversion_subprocess_env_with_venv_resets_venv_and_python_vars(self) -> None:
        with TemporaryDirectory() as td:
            root = Path(td).resolve()
            vpy = root / "venv" / "bin" / "python"
            vpy.parent.mkdir(parents=True, exist_ok=True)
            vpy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
            vpy.chmod(0o755)
            old = dict(os.environ)
            try:
                os.environ["VIRTUAL_ENV"] = "/tmp/other-venv"
                os.environ["PYTHONHOME"] = "/tmp/bad-home"
                os.environ["PYTHONPATH"] = "/tmp/bad-path"
                os.environ["PATH"] = "/tmp/other-venv/bin" + os.pathsep + old.get("PATH", "")
                env = monitor_server.library_conversion_subprocess_env(root)
            finally:
                os.environ.clear()
                os.environ.update(old)

            venv_res = str((root / "venv").resolve())
            bin_res = str((root / "venv" / "bin").resolve())
            self.assertEqual(env["VIRTUAL_ENV"], venv_res)
            self.assertTrue(env["PATH"].startswith(bin_res + os.pathsep))
            self.assertNotIn("PYTHONHOME", env)
            self.assertNotIn("PYTHONPATH", env)

    def test_library_start_uses_project_venv_python_when_present(self) -> None:
        vpy = self.root / "venv" / "bin" / "python"
        vpy.parent.mkdir(parents=True, exist_ok=True)
        vpy.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        vpy.chmod(0o755)
        _, up = self._upload_epub(b"epub-for-venv-start")
        book_id = up["book"]["id"]
        st, data = self._post_json("/api/library/start", {"id": book_id})
        self.assertEqual(st, 200)
        self.assertTrue(data.get("ok"))
        self.assertEqual(len(self._popen_calls), 1)
        pop_kw = self._popen_calls[0]["kwargs"]
        self.assertIn("env", pop_kw)
        child_env = pop_kw["env"]
        venv_res = str((self.root / "venv").resolve())
        bin_res = str((self.root / "venv" / "bin").resolve())
        self.assertEqual(child_env.get("VIRTUAL_ENV"), venv_res)
        self.assertTrue((child_env.get("PATH") or "").startswith(bin_res + os.pathsep))
        cmd = list(self._popen_calls[0]["args"][0])
        self.assertEqual(cmd[0], str(vpy))

        log_path = self.root / "library" / "runs" / book_id / "conversion.log"
        first_line = log_path.read_text(encoding="utf-8").splitlines()[0]
        self.assertTrue(first_line.startswith("[launch] python="))
        self.assertIn(str(vpy), first_line)

    def test_library_delete_removes_catalog_and_files(self) -> None:
        _, up = self._upload_epub(b"epub-to-delete")
        book_id = up["book"]["id"]
        epub_rel = up["book"]["epub_rel_path"]
        epub_path = self.root / epub_rel
        self.assertTrue(epub_path.is_file())
        orphan = self.root / "library" / "runs" / book_id / "probe.txt"
        orphan.parent.mkdir(parents=True, exist_ok=True)
        orphan.write_text("x", encoding="utf-8")

        st, data = self._post_json("/api/library/delete", {"id": book_id})
        self.assertEqual(st, 200)
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("removed"))
        self.assertEqual(data.get("id"), book_id)
        self.assertEqual(data.get("stopped_pids"), [])

        cat = monitor_server.read_catalog(self.root)
        self.assertEqual(cat.get("books", []), [])
        self.assertFalse(epub_path.exists())
        self.assertFalse((self.root / "library" / "runs" / book_id).exists())

    def test_library_delete_stops_matching_active_conversion(self) -> None:
        _, up = self._upload_epub(b"epub-to-stop")
        book_id = up["book"]["id"]
        run_dir = self.root / "library" / "runs" / book_id / "book-out"
        run_dir.mkdir(parents=True, exist_ok=True)
        cat = monitor_server.read_catalog(self.root)
        for row in cat.get("books", []):
            if row.get("id") == book_id:
                row["run_relpath"] = str(run_dir.relative_to(self.root))
                break
        monitor_server.write_catalog(self.root, cat)

        old_parse = monitor_server.parse_processes
        old_getpgid = monitor_server.os.getpgid
        old_killpg = monitor_server.os.killpg
        killed: list[tuple[int, int]] = []
        try:
            monitor_server.parse_processes = lambda: [  # type: ignore[assignment]
                {"pid": 4242, "cmdline": f"python epub_to_audiobook.py --outdir {run_dir}"}
            ]
            monitor_server.os.getpgid = lambda pid: pid  # type: ignore[assignment]
            monitor_server.os.killpg = lambda pgid, sig: killed.append((pgid, sig))  # type: ignore[assignment]
            st_stop, data_stop = self._post_json("/api/library/stop", {"id": book_id})
            st, data = self._post_json("/api/library/delete", {"id": book_id})
        finally:
            monitor_server.parse_processes = old_parse  # type: ignore[assignment]
            monitor_server.os.getpgid = old_getpgid  # type: ignore[assignment]
            monitor_server.os.killpg = old_killpg  # type: ignore[assignment]

        self.assertEqual(st_stop, 200)
        self.assertTrue(data_stop.get("ok"))
        self.assertEqual(data_stop.get("stopped_pids"), [4242])
        self.assertEqual(data_stop.get("book", {}).get("conversion_status"), "stopped")
        self.assertEqual(st, 200)
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("removed"))
        self.assertEqual(data.get("stopped_pids"), [4242])
        self.assertEqual(killed, [(4242, monitor_server.signal.SIGTERM), (4242, monitor_server.signal.SIGTERM)])
        self.assertFalse((self.root / "library" / "runs" / book_id).exists())

    def test_library_delete_idempotent(self) -> None:
        st, data = self._post_json("/api/library/delete", {"id": "00000000-0000-0000-0000-000000000000"})
        self.assertEqual(st, 200)
        self.assertTrue(data.get("ok"))
        self.assertFalse(data.get("removed"))

    def test_library_delete_removes_optional_cover(self) -> None:
        _, up = self._upload_epub(b"epub-with-cover-path")
        book_id = up["book"]["id"]
        cov = self.root / "library" / "covers" / f"{book_id}.jpg"
        cov.parent.mkdir(parents=True, exist_ok=True)
        cov.write_bytes(b"\xff\xd8\xff\xe0")
        cat = monitor_server.read_catalog(self.root)
        for row in cat.get("books", []):
            if row.get("id") == book_id:
                row["cover_rel_path"] = str(cov.relative_to(self.root))
                break
        monitor_server.write_catalog(self.root, cat)
        self.assertTrue(cov.is_file())

        st, data = self._post_json("/api/library/delete", {"id": book_id})
        self.assertEqual(st, 200)
        self.assertTrue(data.get("ok"))
        self.assertTrue(data.get("removed"))
        self.assertFalse(cov.exists())


if __name__ == "__main__":
    unittest.main()
