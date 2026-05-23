#!/usr/bin/env python3
"""HTTP app server for Audiobook Library (tailnet single-user; no authentication).

Library state lives under ``<root>/library/`` and is independent of ad-hoc ``out*/`` runs.
Pipeline execution still delegates to ``epub_to_audiobook.py``.
"""
from __future__ import annotations

import argparse
import cgi
import json
import os
import re
import signal
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

ROOT = Path(__file__).resolve().parent
DASHBOARD_PATH = ROOT / "dashboard" / "index.html"


def resolve_library_pipeline_python(project_root: Path) -> str:
    """Python executable used to spawn ``epub_to_audiobook.py`` for library conversions.

    Prefer ``<project_root>/venv/bin/python`` when it exists and is executable so the
    pipeline runs with project dependencies (for example ``bs4``) even if the
    dashboard server was started from another interpreter. Falls back to
    ``sys.executable``.
    """
    try:
        candidate = project_root / "venv" / "bin" / "python"
        if candidate.is_file() and os.access(candidate, os.X_OK):
            return str(candidate)
    except OSError:
        pass
    return sys.executable


def library_conversion_subprocess_env(project_root: Path) -> dict[str, str]:
    """Environment dict for ``subprocess.Popen`` when spawning library conversions.

    If ``<project_root>/venv/bin/python`` exists and is executable, returns a copy
    of ``os.environ`` scoped to that venv (``VIRTUAL_ENV``, ``PATH``) and strips
    ``PYTHONHOME`` / ``PYTHONPATH`` so a parent activated into another venv does
    not leak incompatible site-packages into the child.

    Otherwise returns ``dict(os.environ)`` unchanged aside from copying, matching
    ``resolve_library_pipeline_python`` falling back to ``sys.executable``.
    """
    env: dict[str, str] = dict(os.environ)
    try:
        vpy = project_root / "venv" / "bin" / "python"
        if not vpy.is_file() or not os.access(vpy, os.X_OK):
            return env
    except OSError:
        return env

    venv_home = str((project_root / "venv").resolve())
    venv_bin = str((project_root / "venv" / "bin").resolve())
    env["VIRTUAL_ENV"] = venv_home
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    path_val = env.get("PATH", "")
    env["PATH"] = f"{venv_bin}{os.pathsep}{path_val}" if path_val else venv_bin
    return env


def _safe_unlink_file(path: Path) -> None:
    try:
        if path.is_file():
            path.unlink()
    except OSError:
        pass


def _safe_rmtree(path: Path) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
    except OSError:
        pass


def matching_library_run_processes(active_processes: list[dict], run_dir: Path | None, outdir: Path | None) -> list[dict]:
    matches: list[dict] = []
    for proc in active_processes:
        cl = str(proc.get("cmdline") or "")
        if _process_matches_library_run(cl, run_dir, outdir):
            matches.append(proc)
    return matches


def stop_library_run_processes(active_processes: list[dict], run_dir: Path | None, outdir: Path | None) -> list[int]:
    stopped: list[int] = []
    for proc in matching_library_run_processes(active_processes, run_dir, outdir):
        pid = int(proc.get("pid") or 0)
        if pid <= 0:
            continue
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, signal.SIGTERM)
        except ProcessLookupError:
            continue
        except PermissionError:
            continue
        except OSError:
            try:
                os.kill(pid, signal.SIGTERM)
            except OSError:
                continue
        stopped.append(pid)
    return stopped


def stop_library_book_generation(root: Path, book: dict) -> dict:
    root_res = root.resolve()
    run_dir: Path | None = None
    rel = book.get("run_relpath")
    if isinstance(rel, str) and rel:
        try:
            candidate = (root / rel).resolve()
            candidate.relative_to(root_res)
            run_dir = candidate
        except (OSError, ValueError):
            run_dir = None
    outdir = _library_run_outdir(root, book)
    stopped_pids = stop_library_run_processes(parse_processes(), run_dir, outdir)
    return {
        "ok": True,
        "id": book.get("id"),
        "stopped_pids": stopped_pids,
        "stopped": bool(stopped_pids),
    }


def remove_library_book(root: Path, book_id: str) -> dict:
    """Remove a book from ``catalog.json`` and delete its backing files (idempotent).

    Deletes the catalog row, uploaded EPUB, cover image, and ``library/runs/<id>/``.
    Missing files are ignored. If the book id is not in the catalog, returns
    ``removed: false`` with HTTP success semantics for idempotent deletes.
    """
    snapshot: dict | None = None
    with _catalog_lock:
        catalog = read_catalog(root)
        books = catalog.get("books", [])
        book = next((b for b in books if isinstance(b, dict) and b.get("id") == book_id), None)
        if not book:
            return {"ok": True, "removed": False, "id": book_id}
        snapshot = dict(book)
        catalog["books"] = [b for b in books if b.get("id") != book_id]
        write_catalog(root, catalog)

    assert snapshot is not None
    root_res = root.resolve()
    run_dir: Path | None = None
    rel = snapshot.get("run_relpath")
    if isinstance(rel, str) and rel:
        try:
            candidate = (root / rel).resolve()
            candidate.relative_to(root_res)
            run_dir = candidate
        except (OSError, ValueError):
            run_dir = None
    outdir = _library_run_outdir(root, snapshot)
    stopped_pids = stop_library_book_generation(root, snapshot)["stopped_pids"]
    for key in ("epub_rel_path", "cover_rel_path"):
        rel = snapshot.get(key)
        if not rel or not isinstance(rel, str):
            continue
        p = (root / rel).resolve()
        try:
            p.relative_to(root_res)
        except (OSError, ValueError):
            continue
        _safe_unlink_file(p)

    run_base = (root / "library" / "runs" / str(book_id)).resolve()
    try:
        run_base.relative_to(root_res)
    except (OSError, ValueError):
        return {"ok": True, "removed": True, "id": book_id, "stopped_pids": stopped_pids}
    _safe_rmtree(run_base)
    return {"ok": True, "removed": True, "id": book_id, "stopped_pids": stopped_pids}

_catalog_lock = threading.Lock()
_settings_lock = threading.Lock()

# Default app settings (persisted under library/app_settings.json).
# Fields not yet consumed by the pipeline are still stored for future wiring.
DEFAULT_APP_SETTINGS: dict = {
    "version": 1,
    "kokoro_voice": "af_heart",
    "kokoro_workers": 2,
    "rewrite_policy": "script-only",
    "hls_live": True,
    "output_retention": "keep_all",
}

REWRITE_POLICIES = frozenset({"full", "selective", "script-only"})
# Library runs: deterministic cleanup only; no LLM rewrite backend on the CLI.
LIBRARY_REWRITE_POLICY = "script-only"
# If the pipeline writes nothing and no matching process runs for this long, treat as stalled.
STALE_LIBRARY_RUN_QUIET_S = 120


def slugify_title(text: str, limit: int = 80) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = re.sub(r"-+", "-", text).strip("-")
    return (text[:limit] or "book").strip("-")


def library_paths(root: Path) -> tuple[Path, Path, Path, Path]:
    base = root / "library"
    return base, base / "uploads", base / "covers", base / "runs"


def read_catalog(root: Path) -> dict:
    _, _, _, _ = library_paths(root)
    path = root / "library" / "catalog.json"
    data = read_json(path, None)
    if not isinstance(data, dict):
        return {"version": 1, "books": []}
    data.setdefault("version", 1)
    data.setdefault("books", [])
    return data


def write_catalog(root: Path, catalog: dict) -> None:
    path = root / "library" / "catalog.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(catalog, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def _guess_from_filename(raw_name: str) -> tuple[str, str]:
    """Parse 'Title (Author).epub' or 'Title - Author.epub' patterns."""
    base = Path(raw_name).stem.strip()
    # Pattern: Title (Author)
    m = re.match(r"^(.*?)\s*\(([^)]+)\)\s*$", base)
    if m:
        return m.group(1).strip(), m.group(2).strip()
    # Pattern: Title - Author
    parts = base.rsplit(" - ", 1)
    if len(parts) == 2 and len(parts[1]) < 60:
        return parts[0].strip(), parts[1].strip()
    return base, ""


def extract_epub_metadata(epub_path: Path, raw_name: str = "") -> tuple[str, str, bytes | None, dict]:
    """Best-effort title, author, cover bytes, and extra metadata from an EPUB."""
    extra: dict = {}
    file_title, file_author = _guess_from_filename(raw_name) if raw_name else ("", "")
    fallback_title = file_title or epub_path.stem

    try:
        from ebooklib import ITEM_COVER, ITEM_IMAGE
        from ebooklib import epub as el_epub
    except ImportError:
        return fallback_title, file_author, None, extra

    try:
        book = el_epub.read_epub(str(epub_path))
        titles = book.get_metadata("DC", "title") or ()
        title = str(titles[0][0]).strip() if titles else fallback_title
        creators = book.get_metadata("DC", "creator") or ()
        author = str(creators[0][0]).strip() if creators else file_author

        # Pull extra fields when available
        dates = book.get_metadata("DC", "date") or ()
        if dates:
            extra["published_date"] = str(dates[0][0]).strip()
        publishers = book.get_metadata("DC", "publisher") or ()
        if publishers:
            extra["publisher"] = str(publishers[0][0]).strip()
        descriptions = book.get_metadata("DC", "description") or ()
        if descriptions:
            extra["description"] = str(descriptions[0][0]).strip()
        langs = book.get_metadata("DC", "language") or ()
        if langs:
            extra["language"] = str(langs[0][0]).strip()
        identifiers = book.get_metadata("DC", "identifier") or ()
        for ident in identifiers:
            val = str(ident[0]).strip() if ident else ""
            opts = ident[1] if len(ident) > 1 and isinstance(ident[1], dict) else {}
            scheme = opts.get("scheme", "")
            if scheme and val:
                extra.setdefault("identifiers", {})[scheme.lower()] = val
            elif val and (val.startswith("978") or len(val) in (10, 13)):
                extra.setdefault("identifiers", {})["isbn"] = val

        cover_data: bytes | None = None
        for item in book.get_items():
            if item.get_type() == ITEM_COVER:
                cover_data = item.get_content()
                break
        if cover_data is None:
            meta_cover = book.get_metadata("OPF", "cover")
            if meta_cover and meta_cover[0] and meta_cover[0][0]:
                cid = meta_cover[0][0]
                cover_item = book.get_item_by_id(cid)
                if cover_item:
                    cover_data = cover_item.get_content()
        # Last resort: grab the first large image that looks like a cover
        if cover_data is None:
            for item in book.get_items():
                if item.get_type() == ITEM_IMAGE:
                    data = item.get_content()
                    if data and len(data) > 5000:
                        name = (item.get_name() or "").lower()
                        if any(h in name for h in ("cover", "front", "title", "jacket")):
                            cover_data = data
                            break
            if cover_data is None:
                # Just take the largest image
                best = None
                best_size = 0
                for item in book.get_items():
                    if item.get_type() == ITEM_IMAGE:
                        data = item.get_content()
                        if data and len(data) > best_size:
                            best_size = len(data)
                            best = data
                cover_data = best

        return title or fallback_title, author, cover_data, extra
    except Exception:
        return fallback_title, file_author, None, extra


def _enrich_from_google_books(title: str, author: str) -> dict:
    """Fetch cover URL and extra metadata from Google Books API."""
    enriched: dict = {}
    try:
        query = f"intitle:{urllib.parse.quote(title)}"
        if author:
            query += f"+inauthor:{urllib.parse.quote(author)}"
        url = f"https://www.googleapis.com/books/v1/volumes?q={query}&maxResults=1"
        req = urllib.request.Request(url, headers={"Accept": "application/json"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            if resp.status != 200:
                return enriched
            data = json.loads(resp.read().decode("utf-8"))
        items = data.get("items", [])
        if not items:
            return enriched
        vol = items[0].get("volumeInfo", {})
        if not enriched.get("title") and vol.get("title"):
            enriched["title"] = vol["title"]
        if not enriched.get("author") and vol.get("authors"):
            enriched["author"] = ", ".join(vol["authors"])
        if not enriched.get("published_date") and vol.get("publishedDate"):
            enriched["published_date"] = vol["publishedDate"]
        if not enriched.get("description") and vol.get("description"):
            enriched["description"] = vol["description"]
        if not enriched.get("publisher") and vol.get("publisher"):
            enriched["publisher"] = vol["publisher"]
        if not enriched.get("page_count") and vol.get("pageCount"):
            enriched["page_count"] = vol["pageCount"]
        img = vol.get("imageLinks", {})
        if img.get("thumbnail"):
            enriched["cover_url"] = img["thumbnail"]
        elif img.get("smallThumbnail"):
            enriched["cover_url"] = img["smallThumbnail"]
    except Exception:
        pass
    return enriched


def _download_cover_bytes(url: str) -> bytes | None:
    try:
        req = urllib.request.Request(url, headers={"Accept": "image/*"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                return resp.read()
    except Exception:
        pass
    return None


def _library_run_outdir(root: Path, book: dict) -> Path | None:
    bid = book.get("id")
    if not bid:
        return None
    p = (root / "library" / "runs" / str(bid)).resolve()
    return p if p.is_dir() else None


def _run_dir_activity_mtime(run_dir: Path) -> float:
    mt = 0.0
    for candidate in (run_dir, run_dir / "status.json", run_dir / "events.jsonl"):
        try:
            if candidate.exists():
                mt = max(mt, candidate.stat().st_mtime)
        except OSError:
            continue
    return mt


def _peek_last_jsonl_event(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        with path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            if size <= 0:
                return None
            chunk = min(size, 8192)
            fh.seek(-chunk, os.SEEK_END)
            tail = fh.read().splitlines()
        for raw in reversed(tail):
            line = raw.strip()
            if not line:
                continue
            try:
                return json.loads(line.decode("utf-8"))
            except Exception:
                continue
    except Exception:
        return None
    return None


def _process_matches_library_run(cmdline: str, run_dir: Path | None, outdir: Path | None) -> bool:
    if "epub_to_audiobook.py" not in cmdline:
        return False
    if run_dir is not None:
        try:
            rs = str(run_dir.resolve())
            if rs in cmdline:
                return True
        except OSError:
            pass
    if outdir is not None:
        try:
            os_part = str(outdir.resolve())
            if os_part in cmdline:
                return True
        except OSError:
            pass
    return False


def library_run_process_live(active_processes: list[dict], run_dir: Path | None, outdir: Path | None) -> bool:
    return bool(matching_library_run_processes(active_processes, run_dir, outdir))


def library_run_process_paused(active_processes: list[dict], run_dir: Path | None, outdir: Path | None) -> bool:
    """True if matching processes exist but are in stopped (T) state."""
    for proc in matching_library_run_processes(active_processes, run_dir, outdir):
        if proc.get("state") == "T":
            return True
    return False


def compute_book_conversion_state(root: Path, book: dict, active_processes: list[dict]) -> dict:
    """Derive conversion_status plus lightweight generation evidence (single-user library)."""
    root_res = root.resolve()
    rel = book.get("run_relpath")
    idle = {
        "conversion_status": "idle",
        "generation_is_live": False,
        "generation_updated_at": None,
        "generation_last_event": None,
        "generation_current": None,
    }
    if not rel:
        return idle
    try:
        run_dir = (root / rel).resolve()
        run_dir.relative_to(root_res)
    except (OSError, ValueError):
        return idle

    outdir = _library_run_outdir(root, book)
    run_exists = run_dir.is_dir()
    live = library_run_process_live(active_processes, run_dir if run_exists else None, outdir)
    paused = library_run_process_paused(active_processes, run_dir if run_exists else None, outdir)

    if not run_exists:
        if paused:
            return {
                "conversion_status": "paused",
                "generation_is_live": False,
                "generation_updated_at": None,
                "generation_last_event": None,
                "generation_current": None,
            }
        if live:
            return {
                "conversion_status": "running",
                "generation_is_live": True,
                "generation_updated_at": None,
                "generation_last_event": None,
                "generation_current": None,
            }
        if outdir is not None:
            quiet = time.time() - outdir.stat().st_mtime
            if quiet > STALE_LIBRARY_RUN_QUIET_S:
                return {
                    "conversion_status": "stalled",
                    "generation_is_live": False,
                    "generation_updated_at": iso_mtime(outdir),
                    "generation_last_event": None,
                    "generation_current": None,
                }
        return {
            "conversion_status": "starting",
            "generation_is_live": False,
            "generation_updated_at": iso_mtime(outdir) if outdir else None,
            "generation_last_event": None,
            "generation_current": None,
        }

    status = read_json(run_dir / "status.json")
    events_path = run_dir / "events.jsonl"
    last_ev = _peek_last_jsonl_event(events_path)
    last_event_summary = None
    if isinstance(last_ev, dict):
        ev = last_ev.get("event")
        ts = last_ev.get("ts")
        if ev is not None or ts is not None:
            last_event_summary = f"{ev or 'event'} · {ts or ''}".strip(" ·")

    updated_at = None
    generation_current = None
    if isinstance(status, dict):
        ua = status.get("updated_at")
        if isinstance(ua, str) and ua.strip():
            updated_at = ua.strip()
        cur = status.get("current")
        if isinstance(cur, dict):
            generation_current = cur

    if updated_at is None:
        try:
            updated_at = iso_mtime(run_dir / "status.json") if (run_dir / "status.json").exists() else iso_mtime(run_dir)
        except OSError:
            updated_at = None

    if not status:
        if paused:
            return {
                "conversion_status": "paused",
                "generation_is_live": False,
                "generation_updated_at": updated_at,
                "generation_last_event": last_event_summary,
                "generation_current": generation_current,
            }
        if live:
            return {
                "conversion_status": "running",
                "generation_is_live": True,
                "generation_updated_at": updated_at,
                "generation_last_event": last_event_summary,
                "generation_current": generation_current,
            }
        quiet = time.time() - _run_dir_activity_mtime(run_dir)
        if quiet > STALE_LIBRARY_RUN_QUIET_S:
            return {
                "conversion_status": "stalled",
                "generation_is_live": False,
                "generation_updated_at": updated_at,
                "generation_last_event": last_event_summary,
                "generation_current": generation_current,
            }
        return {
            "conversion_status": "starting",
            "generation_is_live": False,
            "generation_updated_at": updated_at,
            "generation_last_event": last_event_summary,
            "generation_current": generation_current,
        }

    if status.get("error"):
        return {
            "conversion_status": "error",
            "generation_is_live": live,
            "generation_updated_at": updated_at,
            "generation_last_event": last_event_summary,
            "generation_current": generation_current,
        }
    if status.get("phase") == "done" or status.get("output"):
        return {
            "conversion_status": "ready",
            "generation_is_live": False,
            "generation_updated_at": updated_at,
            "generation_last_event": last_event_summary,
            "generation_current": generation_current,
        }

    if paused:
        return {
            "conversion_status": "paused",
            "generation_is_live": False,
            "generation_updated_at": updated_at,
            "generation_last_event": last_event_summary,
            "generation_current": generation_current,
        }
    if live:
        return {
            "conversion_status": "running",
            "generation_is_live": True,
            "generation_updated_at": updated_at,
            "generation_last_event": last_event_summary,
            "generation_current": generation_current,
        }

    quiet = time.time() - _run_dir_activity_mtime(run_dir)
    if quiet > STALE_LIBRARY_RUN_QUIET_S:
        return {
            "conversion_status": "stalled",
            "generation_is_live": False,
            "generation_updated_at": updated_at,
            "generation_last_event": last_event_summary,
            "generation_current": generation_current,
        }
    return {
        "conversion_status": "stopped",
        "generation_is_live": False,
        "generation_updated_at": updated_at,
        "generation_last_event": last_event_summary,
        "generation_current": generation_current,
    }


def merge_run_into_book(root: Path, book: dict) -> dict:
    out = dict(book)
    rel = book.get("run_relpath")
    if not rel:
        return out
    run_dir = (root / rel).resolve()
    if not run_dir.is_dir():
        return out
    summary = run_summary(run_dir)
    events = []
    events_path = run_dir / "events.jsonl"
    if events_path.exists():
        try:
            lines = events_path.read_text(encoding="utf-8").splitlines()[-40:]
            events = [json.loads(line) for line in lines if line.strip()]
        except Exception:
            events = []
    summary["events"] = events
    summary["path"] = str(run_dir.relative_to(root.resolve()))
    final_output = summary.get("output")
    summary["downloads"] = {"final_audio": None}
    if final_output and Path(final_output).exists():
        r = str(Path(final_output).resolve().relative_to(root.resolve()))
        summary["downloads"]["final_audio"] = f"/media?path={quote(r)}"
    for chapter in summary.get("chapters", []) or []:
        wav_path = chapter.get("wav")
        if wav_path and Path(wav_path).exists():
            r = str(Path(wav_path).resolve().relative_to(root.resolve()))
            chapter["audio_url"] = f"/media?path={quote(r)}"
            chapter["download_url"] = chapter["audio_url"]
        m4a_path = chapter.get("m4a")
        if m4a_path and Path(m4a_path).exists():
            r = str(Path(m4a_path).resolve().relative_to(root.resolve()))
            chapter["audio_m4a_url"] = f"/media?path={quote(r)}"
            chapter["download_m4a_url"] = chapter["audio_m4a_url"]
        hls_playlist = chapter.get("hls_playlist")
        if hls_playlist and Path(hls_playlist).exists():
            r = str(Path(hls_playlist).resolve().relative_to(root.resolve()))
            chapter["hls_url"] = f"/media?path={quote(r)}"
    out["run"] = summary
    return out


def rewrite_m3u8_with_absolute_media_urls(playlist_file: Path, root: Path) -> bytes:
    """Rewrite segment lines to /media?path=… so players resolve segments from this server."""
    raw = playlist_file.read_text(encoding="utf-8")
    root_res = root.resolve()
    pl_dir = playlist_file.parent.resolve()
    out_lines: list[str] = []
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            out_lines.append(line)
            continue
        if "://" in stripped:
            out_lines.append(line)
            continue
        seg_path = (pl_dir / stripped).resolve()
        try:
            rel = str(seg_path.relative_to(root_res))
        except ValueError:
            out_lines.append(line)
            continue
        out_lines.append(f"/media?path={quote(rel)}")
    body = "\n".join(out_lines)
    if not body.endswith("\n"):
        body += "\n"
    return body.encode("utf-8")


def read_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def annotate_chapter_timeline(chapters: list[dict] | None) -> list[dict]:
    if not isinstance(chapters, list):
        return []
    out: list[dict] = []
    cursor = 0.0
    for raw in chapters:
        if not isinstance(raw, dict):
            continue
        chapter = dict(raw)
        dur = chapter.get("duration_s")
        try:
            dur_f = float(dur) if dur is not None else None
        except (TypeError, ValueError):
            dur_f = None
        if dur_f is not None and dur_f >= 0:
            chapter["start_s"] = round(cursor, 6)
            cursor += dur_f
            chapter["end_s"] = round(cursor, 6)
        out.append(chapter)
    return out


def settings_path(root: Path) -> Path:
    return root / "library" / "app_settings.json"


def read_app_settings(root: Path) -> dict:
    path = settings_path(root)
    data = read_json(path, None)
    out = dict(DEFAULT_APP_SETTINGS)
    if isinstance(data, dict):
        for k, v in data.items():
            if k in DEFAULT_APP_SETTINGS:
                out[k] = v
    out["version"] = int(out.get("version") or 1)
    # HLS/live pipeline is always used for library runs; ignore legacy persisted false.
    out["hls_live"] = True
    # Library conversions always use the safe fixed runtime path regardless of stale settings.
    out["kokoro_workers"] = 2
    rp = out.get("rewrite_policy")
    if rp not in REWRITE_POLICIES:
        out["rewrite_policy"] = DEFAULT_APP_SETTINGS["rewrite_policy"]
    return out


def write_app_settings(root: Path, settings: dict) -> None:
    path = settings_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(settings, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)


def merge_app_settings(base: dict, body: dict) -> dict:
    """Apply a partial JSON body onto persisted settings (validated, tailnet-trusted)."""
    cur = dict(base)
    voice = body.get("kokoro_voice")
    if isinstance(voice, str) and voice.strip():
        cur["kokoro_voice"] = voice.strip()[:80]
    ort = body.get("output_retention")
    if ort in ("keep_all", "delete_intermediates_after_complete"):
        cur["output_retention"] = ort
    cur["version"] = int(cur.get("version") or 1)
    cur["hls_live"] = True
    cur["kokoro_workers"] = 2
    rp = body.get("rewrite_policy")
    if rp in REWRITE_POLICIES:
        cur["rewrite_policy"] = rp
    elif "rewrite_policy" in body:
        cur["rewrite_policy"] = DEFAULT_APP_SETTINGS["rewrite_policy"]
    return cur


def iso_mtime(path: Path) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z", time.localtime(path.stat().st_mtime))


def chapter_dirs(book_dir: Path) -> list[Path]:
    root = book_dir / "chapters"
    if not root.exists():
        return []
    return sorted([p for p in root.iterdir() if p.is_dir()])


def count_named_files(folder: Path, suffix: str) -> int:
    if not folder.exists():
        return 0
    total = 0
    for path in folder.iterdir():
        if not path.is_file() or path.suffix != suffix:
            continue
        if path.name.endswith("-gap" + suffix):
            continue
        total += 1
    return total


def parse_processes() -> list[dict]:
    processes = []
    proc_root = Path("/proc")
    for proc_dir in proc_root.iterdir():
        if not proc_dir.name.isdigit():
            continue
        try:
            cmdline = (proc_dir / "cmdline").read_bytes().replace(b"\x00", b" ").decode("utf-8").strip()
            if "epub_to_audiobook.py" not in cmdline:
                continue
            statm = (proc_dir / "statm").read_text().split()
            rss_pages = int(statm[1]) if len(statm) > 1 else 0
            rss_mb = round(rss_pages * os.sysconf("SC_PAGE_SIZE") / (1024 * 1024), 1)
            # Read state from /proc/<pid>/status (e.g., "State: T (stopped)")
            state = ""
            try:
                for line in (proc_dir / "status").read_text().splitlines():
                    if line.startswith("State:"):
                        state = line.split(None, 1)[1].strip().split()[0]
                        break
            except Exception:
                pass
            processes.append(
                {
                    "pid": int(proc_dir.name),
                    "cmdline": cmdline,
                    "rss_mb": rss_mb,
                    "state": state,
                }
            )
        except Exception:
            continue
    return processes


def _send_signal_to_library_run(active_processes: list[dict], run_dir: Path | None, outdir: Path | None, sig: int) -> list[int]:
    """Send a signal (e.g., SIGSTOP, SIGCONT) to matching library run processes."""
    affected: list[int] = []
    for proc in matching_library_run_processes(active_processes, run_dir, outdir):
        pid = int(proc.get("pid") or 0)
        if pid <= 0:
            continue
        try:
            pgid = os.getpgid(pid)
            os.killpg(pgid, sig)
        except ProcessLookupError:
            continue
        except PermissionError:
            continue
        except OSError:
            try:
                os.kill(pid, sig)
            except OSError:
                continue
        affected.append(pid)
    return affected


def pause_library_run_processes(active_processes: list[dict], run_dir: Path | None, outdir: Path | None) -> list[int]:
    return _send_signal_to_library_run(active_processes, run_dir, outdir, signal.SIGSTOP)


def resume_library_run_processes(active_processes: list[dict], run_dir: Path | None, outdir: Path | None) -> list[int]:
    return _send_signal_to_library_run(active_processes, run_dir, outdir, signal.SIGCONT)


def get_system_metrics(root: Path) -> dict:
    uptime_s = 0.0
    try:
        uptime_s = float(Path("/proc/uptime").read_text().split()[0])
    except Exception:
        pass

    meminfo = {}
    try:
        for line in Path("/proc/meminfo").read_text().splitlines():
            key, value = line.split(":", 1)
            meminfo[key] = value.strip()
    except Exception:
        meminfo = {}

    def mem_kb(key: str) -> int:
        raw = meminfo.get(key, "0 kB").split()[0]
        try:
            return int(raw)
        except ValueError:
            return 0

    total_kb = mem_kb("MemTotal")
    avail_kb = mem_kb("MemAvailable")
    used_kb = max(total_kb - avail_kb, 0)

    disk = shutil.disk_usage(root)
    load1, load5, load15 = os.getloadavg()

    return {
        "uptime_s": round(uptime_s, 1),
        "cpu_load": {"1m": round(load1, 2), "5m": round(load5, 2), "15m": round(load15, 2)},
        "memory": {
            "total_gb": round(total_kb / 1024 / 1024, 2),
            "used_gb": round(used_kb / 1024 / 1024, 2),
            "available_gb": round(avail_kb / 1024 / 1024, 2),
            "used_pct": round((used_kb / total_kb) * 100, 1) if total_kb else 0.0,
        },
        "disk": {
            "total_gb": round(disk.total / 1024 / 1024 / 1024, 2),
            "used_gb": round((disk.total - disk.free) / 1024 / 1024 / 1024, 2),
            "free_gb": round(disk.free / 1024 / 1024 / 1024, 2),
            "used_pct": round(((disk.total - disk.free) / disk.total) * 100, 1) if disk.total else 0.0,
        },
        "active_processes": parse_processes(),
    }


def infer_legacy_status(book_dir: Path) -> dict:
    manifest = read_json(book_dir / "manifest.json", {}) or {}
    chapters = []
    total_chunks = 0
    rewrite_done = 0
    tts_done = 0
    empty_rewrites = 0
    latest_chapter = None
    latest_mtime = 0.0

    for chapter_dir in chapter_dirs(book_dir):
        cache = read_json(chapter_dir / "rewrite-cache.json", {}) or {}
        cache_chunks = cache.get("chunks", {}) if isinstance(cache, dict) else {}
        txt_count = count_named_files(chapter_dir, ".txt")
        wav_count = count_named_files(chapter_dir, ".wav")
        chunk_total = max(txt_count, wav_count, len(cache_chunks))
        empty_count = sum(1 for item in cache_chunks.values() if not str(item.get("rewritten_text", "")).strip())
        chapter_info = {
            "index": int(chapter_dir.name.split("-", 1)[0]),
            "title": chapter_dir.name.split("-", 1)[1].replace("-", " ").title() if "-" in chapter_dir.name else chapter_dir.name,
            "slug": chapter_dir.name,
            "status": "completed" if manifest.get("output") else "running",
            "total_chunks": chunk_total,
            "rewrite_completed_chunks": max(txt_count, len(cache_chunks)),
            "tts_completed_chunks": wav_count,
            "rewrite_cache_hits": 0,
            "rewrite_cache_misses": len(cache_chunks),
            "rewrite_elapsed_s": round(sum(float(v.get("rewrite_elapsed_s", 0.0)) for v in cache_chunks.values()), 3),
            "tts_elapsed_s": 0.0,
            "wall_s": 0.0,
            "empty_rewrite_chunks": empty_count,
        }
        chapters.append(chapter_info)
        total_chunks += chunk_total
        rewrite_done += chapter_info["rewrite_completed_chunks"]
        tts_done += chapter_info["tts_completed_chunks"]
        empty_rewrites += empty_count
        chapter_mtime = chapter_dir.stat().st_mtime
        if chapter_mtime > latest_mtime:
            latest_mtime = chapter_mtime
            latest_chapter = chapter_info

    phase = "done" if manifest.get("output") else ("tts" if tts_done else "rewriting")
    current = {
        "chapter_index": latest_chapter["index"] if latest_chapter else None,
        "chapter_title": latest_chapter["title"] if latest_chapter else None,
        "chapter_slug": latest_chapter["slug"] if latest_chapter else None,
        "chunk_index": latest_chapter["rewrite_completed_chunks"] if latest_chapter else None,
        "chunk_total": latest_chapter["total_chunks"] if latest_chapter else None,
        "phase": phase,
    }
    return {
        "title": manifest.get("title", book_dir.name.replace("-", " ").title()),
        "source": manifest.get("source"),
        "book_dir": str(book_dir),
        "mode": manifest.get("mode", "legacy"),
        "chapter_selection": manifest.get("chapter_selection"),
        "tts_engine": manifest.get("tts_engine", "unknown"),
        "rewrite_backend": manifest.get("rewrite_backend", "unknown"),
        "started_at": iso_mtime(book_dir),
        "updated_at": iso_mtime(book_dir),
        "elapsed_s": max(time.time() - book_dir.stat().st_mtime, 0.0),
        "phase": phase,
        "error": None,
        "output": manifest.get("output"),
        "progress": {
            "total_chapters": len(chapters),
            "completed_chapters": len(manifest.get("chapters", [])) if manifest else 0,
            "total_chunks": total_chunks,
            "rewrite_completed_chunks": rewrite_done,
            "tts_completed_chunks": tts_done,
        },
        "current": current,
        "chapters": chapters,
        "anomalies": ([{"type": "empty_rewrite_chunks", "count": empty_rewrites}] if empty_rewrites else []),
        "legacy": True,
    }


def run_summary(book_dir: Path) -> dict:
    status_path = book_dir / "status.json"
    status = read_json(status_path)
    if status:
        status["legacy"] = False
        manifest = read_json(book_dir / "manifest.json", {}) or {}
        manifest_chapters = {item.get("index"): item for item in manifest.get("chapters", []) if isinstance(item, dict)}
        for chapter in status.get("chapters", []) or []:
            record = manifest_chapters.get(chapter.get("index"), {})
            wav_path = record.get("wav")
            if wav_path:
                chapter["wav"] = wav_path
                try:
                    chapter["wav_exists"] = Path(wav_path).exists()
                except Exception:
                    chapter["wav_exists"] = False
            if record.get("m4a"):
                chapter["m4a"] = record.get("m4a")
            if record.get("hls_playlist"):
                chapter["hls_playlist"] = record.get("hls_playlist")
            if record.get("duration_s") is not None:
                chapter["duration_s"] = record.get("duration_s")
        status["chapters"] = annotate_chapter_timeline(status.get("chapters", []) or [])
        if manifest.get("output"):
            status["output"] = manifest.get("output")
        return status
    return infer_legacy_status(book_dir)


def _collect_book_run_dirs(parent: Path, runs: list[Path]) -> None:
    if not parent.is_dir():
        return
    for child in parent.iterdir():
        if not child.is_dir():
            continue
        if (child / "status.json").exists() or (child / "manifest.json").exists() or (child / "chapters").exists():
            runs.append(child)


def list_run_dirs(root: Path) -> list[Path]:
    runs: list[Path] = []
    for out_dir in sorted(root.glob("out*")):
        if not out_dir.is_dir():
            continue
        _collect_book_run_dirs(out_dir, runs)

    lib_runs = root / "library" / "runs"
    if lib_runs.is_dir():
        for book_run in lib_runs.iterdir():
            if not book_run.is_dir():
                continue
            _collect_book_run_dirs(book_run, runs)

    runs.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return runs


def make_run_list(root: Path) -> list[dict]:
    items = []
    for run_dir in list_run_dirs(root):
        summary = run_summary(run_dir)
        items.append(
            {
                "name": run_dir.name,
                "path": str(run_dir.relative_to(root)),
                "title": summary.get("title", run_dir.name),
                "phase": summary.get("phase", "unknown"),
                "updated_at": summary.get("updated_at"),
                "legacy": summary.get("legacy", False),
                "mode": summary.get("mode"),
            }
        )
    return items


def resolve_run_path(root: Path, raw_path: str | None) -> Path | None:
    if not raw_path:
        runs = list_run_dirs(root)
        return runs[0] if runs else None
    candidate = (root / unquote(raw_path)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() and candidate.is_dir() else None


def resolve_root_relative_path(root: Path, raw_path: str | None) -> Path | None:
    if not raw_path:
        return None
    candidate = (root / unquote(raw_path)).resolve()
    try:
        candidate.relative_to(root.resolve())
    except ValueError:
        return None
    return candidate if candidate.exists() else None


class Handler(BaseHTTPRequestHandler):
    root = ROOT

    def _send_json(self, payload: dict | list, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, body: str, status: int = 200, content_type: str = "text/html; charset=utf-8") -> None:
        data = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _content_type_for_path(self, path: Path) -> str:
        if path.suffix == ".wav":
            return "audio/wav"
        if path.suffix == ".m4b":
            return "audio/mp4"
        if path.suffix == ".mp3":
            return "audio/mpeg"
        if path.suffix == ".m4a":
            return "audio/mp4"
        if path.suffix == ".m3u8":
            return "application/vnd.apple.mpegurl"
        if path.suffix == ".epub":
            return "application/epub+zip"
        return "application/octet-stream"

    def _parse_range_header(self, size: int) -> tuple[int, int] | None:
        header = self.headers.get("Range")
        if not header:
            return None
        m = re.fullmatch(r"bytes=(\d*)-(\d*)", header.strip())
        if not m:
            return None
        start_raw, end_raw = m.groups()
        if not start_raw and not end_raw:
            return None
        if start_raw:
            start = int(start_raw)
            end = int(end_raw) if end_raw else size - 1
        else:
            suffix_len = int(end_raw)
            if suffix_len <= 0:
                return None
            if suffix_len >= size:
                start = 0
            else:
                start = size - suffix_len
            end = size - 1
        if start < 0 or start >= size:
            raise ValueError("range start out of bounds")
        end = min(end, size - 1)
        if end < start:
            raise ValueError("range end before start")
        return start, end

    def _serve_bytes(self, data: bytes, content_type: str, filename: str, *, allow_ranges: bool = True, write_body: bool = True) -> None:
        total = len(data)
        status = 200
        body = data
        content_range = None
        if allow_ranges and total > 0:
            try:
                requested = self._parse_range_header(total)
            except ValueError:
                self.send_response(416)
                self.send_header("Content-Range", f"bytes */{total}")
                self.send_header("Accept-Ranges", "bytes")
                self.send_header("Cache-Control", "no-store")
                self.send_header("Content-Length", "0")
                self.end_headers()
                return
            if requested is not None:
                start, end = requested
                body = data[start : end + 1]
                status = 206
                content_range = f"bytes {start}-{end}/{total}"
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Disposition", f"inline; filename={quote(filename)}")
        if content_range:
            self.send_header("Content-Range", content_range)
        self.end_headers()
        if write_body:
            self.wfile.write(body)

    def _serve_file(self, path: Path, *, rewrite_m3u8: bool = False, write_body: bool = True) -> None:
        content_type = self._content_type_for_path(path)
        if rewrite_m3u8:
            data = rewrite_m3u8_with_absolute_media_urls(path, self.root)
        else:
            data = path.read_bytes()
        self._serve_bytes(data, content_type, path.name, allow_ranges=True, write_body=write_body)

    def _read_json_body(self, max_len: int = 256_000) -> dict | None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            return None
        if length <= 0 or length > max_len:
            return None
        raw = self.rfile.read(length)
        try:
            val = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        return val if isinstance(val, dict) else None

    def _library_public_book(self, book: dict, *, active_processes: list[dict] | None = None) -> dict:
        """Shape returned from APIs (paths are repo-relative, safe for this single-user app)."""
        b = dict(book)
        cover = b.get("cover_rel_path")
        b["cover_url"] = f"/media?path={quote(cover)}" if cover else None
        procs = active_processes if active_processes is not None else parse_processes()
        conv = compute_book_conversion_state(self.root, book, procs)
        b["conversion_status"] = conv["conversion_status"]
        b["generation_is_live"] = conv["generation_is_live"]
        b["generation_updated_at"] = conv["generation_updated_at"]
        b["generation_last_event"] = conv["generation_last_event"]
        b["generation_current"] = conv["generation_current"]
        if not isinstance(b.get("reading_bookmarks"), list):
            b["reading_bookmarks"] = []
        if not isinstance(b.get("listening_bookmarks"), list):
            b["listening_bookmarks"] = []
        if not isinstance(b.get("notes"), list):
            b["notes"] = []
        return b

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path in {"/", "/index.html"}:
            self._send_text(DASHBOARD_PATH.read_text(encoding="utf-8"))
            return
        if parsed.path == "/api/library":
            catalog = read_catalog(self.root)
            procs = parse_processes()
            books = [self._library_public_book(b, active_processes=procs) for b in catalog.get("books", []) if isinstance(b, dict)]
            books.sort(key=lambda x: x.get("added_at") or "", reverse=True)
            self._send_json({"books": books})
            return
        if parsed.path == "/api/library/book":
            qs = parse_qs(parsed.query)
            book_id = (qs.get("id") or [None])[0]
            if not book_id:
                self._send_json({"error": "missing id"}, status=400)
                return
            catalog = read_catalog(self.root)
            book = next((b for b in catalog.get("books", []) if b.get("id") == book_id), None)
            if not book:
                self._send_json({"error": "book not found"}, status=404)
                return
            want_run = (qs.get("include_run") or ["1"])[0] not in {"0", "false", "no"}
            payload = self._library_public_book(book)
            if want_run:
                payload = merge_run_into_book(self.root, payload)
            self._send_json({"book": payload})
            return
        if parsed.path == "/api/library/epub":
            qs = parse_qs(parsed.query)
            book_id = (qs.get("id") or [None])[0]
            if not book_id:
                self._send_json({"error": "missing id"}, status=400)
                return
            catalog = read_catalog(self.root)
            book = next((b for b in catalog.get("books", []) if b.get("id") == book_id), None)
            if not book:
                self._send_json({"error": "book not found"}, status=404)
                return
            rel = book.get("epub_rel_path")
            if not rel:
                self._send_json({"error": "no epub"}, status=404)
                return
            epub_path = (self.root / rel).resolve()
            try:
                epub_path.relative_to(self.root.resolve())
            except ValueError:
                self._send_json({"error": "invalid path"}, status=400)
                return
            if not epub_path.is_file():
                self._send_json({"error": "epub missing on disk"}, status=404)
                return
            self._serve_file(epub_path)
            return
        if parsed.path == "/api/runs":
            self._send_json({"runs": make_run_list(self.root)})
            return
        if parsed.path == "/api/system":
            self._send_json(get_system_metrics(self.root))
            return
        if parsed.path == "/api/settings":
            self._send_json({"settings": read_app_settings(self.root)})
            return
        if parsed.path == "/api/run":
            qs = parse_qs(parsed.query)
            run_dir = resolve_run_path(self.root, qs.get("path", [None])[0])
            if run_dir is None:
                self._send_json({"error": "run not found"}, status=404)
                return
            payload = run_summary(run_dir)
            events = []
            events_path = run_dir / "events.jsonl"
            if events_path.exists():
                try:
                    lines = events_path.read_text(encoding="utf-8").splitlines()[-40:]
                    events = [json.loads(line) for line in lines if line.strip()]
                except Exception:
                    events = []
            payload["events"] = events
            payload["path"] = str(run_dir.relative_to(self.root))
            final_output = payload.get("output")
            payload["downloads"] = {"final_audio": None}
            if final_output and Path(final_output).exists():
                rel = str(Path(final_output).resolve().relative_to(self.root.resolve()))
                payload["downloads"]["final_audio"] = f"/media?path={quote(rel)}"
            for chapter in payload.get("chapters", []) or []:
                wav_path = chapter.get("wav")
                if wav_path and Path(wav_path).exists():
                    rel = str(Path(wav_path).resolve().relative_to(self.root.resolve()))
                    chapter["audio_url"] = f"/media?path={quote(rel)}"
                    chapter["download_url"] = chapter["audio_url"]
                m4a_path = chapter.get("m4a")
                if m4a_path and Path(m4a_path).exists():
                    rel = str(Path(m4a_path).resolve().relative_to(self.root.resolve()))
                    chapter["audio_m4a_url"] = f"/media?path={quote(rel)}"
                    chapter["download_m4a_url"] = chapter["audio_m4a_url"]
                hls_playlist = chapter.get("hls_playlist")
                if hls_playlist and Path(hls_playlist).exists():
                    rel = str(Path(hls_playlist).resolve().relative_to(self.root.resolve()))
                    chapter["hls_url"] = f"/media?path={quote(rel)}"
            self._send_json(payload)
            return
        if parsed.path == "/media":
            qs = parse_qs(parsed.query)
            media_path = resolve_root_relative_path(self.root, qs.get("path", [None])[0])
            if media_path is None or not media_path.is_file():
                self._send_json({"error": "media not found"}, status=404)
                return
            self._serve_file(media_path, rewrite_m3u8=media_path.suffix == ".m3u8")
            return
        self._send_json({"error": f"unknown path: {parsed.path}"}, status=404)

    def do_HEAD(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path == "/media":
            qs = parse_qs(parsed.query)
            media_path = resolve_root_relative_path(self.root, qs.get("path", [None])[0])
            if media_path is None or not media_path.is_file():
                self._send_json({"error": "media not found"}, status=404)
                return
            self._serve_file(media_path, rewrite_m3u8=media_path.suffix == ".m3u8", write_body=False)
            return
        if parsed.path == "/api/library/epub":
            qs = parse_qs(parsed.query)
            book_id = (qs.get("id") or [None])[0]
            if not book_id:
                self._send_json({"error": "missing id"}, status=400)
                return
            catalog = read_catalog(self.root)
            book = next((b for b in catalog.get("books", []) if b.get("id") == book_id), None)
            if not book:
                self._send_json({"error": "book not found"}, status=404)
                return
            rel = book.get("epub_rel_path")
            if not rel:
                self._send_json({"error": "no epub"}, status=404)
                return
            epub_path = (self.root / rel).resolve()
            try:
                epub_path.relative_to(self.root.resolve())
            except ValueError:
                self._send_json({"error": "invalid path"}, status=400)
                return
            if not epub_path.is_file():
                self._send_json({"error": "epub missing on disk"}, status=404)
                return
            self._serve_file(epub_path, write_body=False)
            return
        self.send_error(501, "Unsupported method ('HEAD')")

    def do_POST(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        root = self.root

        if parsed.path == "/api/library/upload":
            try:
                clen = int(self.headers.get("Content-Length", "0"))
            except ValueError:
                clen = 0
            max_upload = 280 * 1024 * 1024
            if clen <= 0 or clen > max_upload:
                self._send_json({"error": "invalid content length"}, status=400)
                return
            environ = {
                "REQUEST_METHOD": "POST",
                "CONTENT_TYPE": self.headers.get("Content-Type", ""),
                "CONTENT_LENGTH": str(clen),
            }
            form = cgi.FieldStorage(fp=self.rfile, headers=self.headers, environ=environ)
            if "file" not in form:
                self._send_json({"error": "expected file field"}, status=400)
                return
            item = form["file"]
            raw_name = getattr(item, "filename", None) or ""
            if not raw_name.lower().endswith(".epub"):
                self._send_json({"error": "only .epub uploads are supported"}, status=400)
                return
            file_data = item.file.read() if item.file else b""
            if not file_data:
                self._send_json({"error": "empty file"}, status=400)
                return
            book_id = str(uuid.uuid4())
            lib_base, uploads, covers, runs = library_paths(root)
            lib_base.mkdir(parents=True, exist_ok=True)
            uploads.mkdir(parents=True, exist_ok=True)
            covers.mkdir(parents=True, exist_ok=True)
            runs.mkdir(parents=True, exist_ok=True)
            epub_path = uploads / f"{book_id}.epub"
            epub_path.write_bytes(file_data)

            title, author, cover_bytes, extra = extract_epub_metadata(epub_path, raw_name)

            # If no embedded cover, try fetching from Google Books
            if not cover_bytes and title:
                enriched = _enrich_from_google_books(title, author)
                if enriched.get("cover_url"):
                    cover_bytes = _download_cover_bytes(enriched["cover_url"])
                if enriched.get("title"):
                    title = enriched["title"]
                if enriched.get("author"):
                    author = enriched["author"]
                extra.update({k: v for k, v in enriched.items() if k != "cover_url"})

            cover_rel = None
            if cover_bytes:
                ext = ".jpg"
                if cover_bytes[:8] == b"\x89PNG\r\n\x1a\n":
                    ext = ".png"
                elif cover_bytes[:4] == b"GIF8":
                    ext = ".gif"
                elif cover_bytes[:4] == b"RIFF" and len(cover_bytes) >= 12 and cover_bytes[8:12] == b"WEBP":
                    ext = ".webp"
                cover_path = covers / f"{book_id}{ext}"
                cover_path.write_bytes(cover_bytes)
                cover_rel = str(cover_path.relative_to(root))

            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            record = {
                "id": book_id,
                "title": title,
                "author": author,
                "source_filename": Path(raw_name).name,
                "epub_rel_path": str(epub_path.relative_to(root)),
                "cover_rel_path": cover_rel,
                "added_at": now,
                "opened_at": now,
                "favorite": False,
                "run_relpath": None,
                "last_error": None,
                "read_cfi": None,
                "read_progress_hint": None,
                "read_updated_at": None,
                "listen_time_s": None,
                "listen_chapter_index": None,
                "listen_abs_time_s": None,
                "listen_chapter_time_s": None,
                "listen_transport": None,
                "listen_timeline_version": None,
                "listen_progress_hint": None,
                "listen_src": None,
                "listen_duration_s": None,
                "listen_updated_at": None,
                "reading_bookmarks": [],
                "listening_bookmarks": [],
                "notes": [],
                "metadata": extra,
            }
            with _catalog_lock:
                catalog = read_catalog(root)
                catalog.setdefault("books", []).append(record)
                write_catalog(root, catalog)
            self._send_json({"book": self._library_public_book(record)})
            return

        if parsed.path == "/api/library/patch":
            body = self._read_json_body()
            if not body:
                self._send_json({"error": "invalid json"}, status=400)
                return
            book_id = body.get("id")
            if not book_id:
                self._send_json({"error": "missing id"}, status=400)
                return
            now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

            def _list(book: dict, key: str) -> list:
                cur = book.get(key)
                if not isinstance(cur, list):
                    book[key] = []
                return book[key]

            with _catalog_lock:
                catalog = read_catalog(root)
                books = catalog.get("books", [])
                book = next((b for b in books if b.get("id") == book_id), None)
                if not book:
                    self._send_json({"error": "book not found"}, status=404)
                    return
                if "favorite" in body:
                    book["favorite"] = bool(body.get("favorite"))
                if "read_cfi" in body:
                    v = body.get("read_cfi")
                    book["read_cfi"] = v if isinstance(v, str) or v is None else book.get("read_cfi")
                if "read_progress_hint" in body:
                    v = body.get("read_progress_hint")
                    book["read_progress_hint"] = v if isinstance(v, str) or v is None else book.get("read_progress_hint")
                if "read_cfi" in body or "read_progress_hint" in body:
                    book["read_updated_at"] = now
                if "listen_time_s" in body:
                    try:
                        book["listen_time_s"] = float(body.get("listen_time_s"))
                    except (TypeError, ValueError):
                        pass
                if "listen_chapter_index" in body:
                    try:
                        book["listen_chapter_index"] = int(body.get("listen_chapter_index"))
                    except (TypeError, ValueError):
                        pass
                if "listen_abs_time_s" in body:
                    try:
                        v = body.get("listen_abs_time_s")
                        book["listen_abs_time_s"] = float(v) if v is not None else None
                    except (TypeError, ValueError):
                        pass
                if "listen_chapter_time_s" in body:
                    try:
                        v = body.get("listen_chapter_time_s")
                        book["listen_chapter_time_s"] = float(v) if v is not None else None
                    except (TypeError, ValueError):
                        pass
                if "listen_transport" in body:
                    v = body.get("listen_transport")
                    if v in (None, "hls", "book", "chapter"):
                        book["listen_transport"] = v
                if "listen_timeline_version" in body:
                    try:
                        book["listen_timeline_version"] = int(body.get("listen_timeline_version"))
                    except (TypeError, ValueError):
                        pass
                if "listen_progress_hint" in body:
                    v = body.get("listen_progress_hint")
                    book["listen_progress_hint"] = v if isinstance(v, str) or v is None else book.get("listen_progress_hint")
                if "listen_src" in body:
                    v = body.get("listen_src")
                    if v in (None, "hls", "final"):
                        book["listen_src"] = v
                if "listen_duration_s" in body:
                    try:
                        book["listen_duration_s"] = float(body.get("listen_duration_s"))
                    except (TypeError, ValueError):
                        pass
                if any(
                    k in body
                    for k in (
                        "listen_time_s",
                        "listen_chapter_index",
                        "listen_abs_time_s",
                        "listen_chapter_time_s",
                        "listen_transport",
                        "listen_timeline_version",
                        "listen_progress_hint",
                        "listen_src",
                        "listen_duration_s",
                    )
                ):
                    book["listen_updated_at"] = now

                ar = body.get("add_reading_bookmark")
                if isinstance(ar, dict):
                    cfi = ar.get("cfi")
                    if isinstance(cfi, str) and cfi.strip():
                        label = ar.get("label")
                        lab = str(label).strip()[:500] if label is not None else ""
                        _list(book, "reading_bookmarks").append(
                            {"id": str(uuid.uuid4()), "cfi": cfi.strip(), "label": lab, "created_at": now}
                        )
                al = body.get("add_listening_bookmark")
                if isinstance(al, dict):
                    ch_i = al.get("chapter_index")
                    t_s = al.get("time_s")
                    ct_s = al.get("chapter_time_s")
                    abs_s = al.get("abs_time_s")
                    try:
                        ch_int = int(ch_i) if ch_i is not None else None
                    except (TypeError, ValueError):
                        ch_int = None
                    try:
                        t_float = float(t_s) if t_s is not None else None
                    except (TypeError, ValueError):
                        t_float = None
                    try:
                        ct_float = float(ct_s) if ct_s is not None else None
                    except (TypeError, ValueError):
                        ct_float = None
                    try:
                        abs_float = float(abs_s) if abs_s is not None else None
                    except (TypeError, ValueError):
                        abs_float = None
                    if ct_float is None and t_float is not None:
                        ct_float = t_float
                    label = al.get("label")
                    lab = str(label).strip()[:500] if label is not None else ""
                    try:
                        tv_bm = int(al.get("timeline_version")) if al.get("timeline_version") is not None else None
                    except (TypeError, ValueError):
                        tv_bm = None
                    if ch_int is not None or t_float is not None or ct_float is not None or abs_float is not None:
                        entry = {
                            "id": str(uuid.uuid4()),
                            "chapter_index": ch_int,
                            "time_s": ct_float if ct_float is not None else t_float,
                            "chapter_time_s": ct_float if ct_float is not None else t_float,
                            "abs_time_s": abs_float,
                            "label": lab,
                            "created_at": now,
                        }
                        if tv_bm is not None:
                            entry["timeline_version"] = tv_bm
                        _list(book, "listening_bookmarks").append(entry)

                rm_r = body.get("remove_reading_bookmark_id")
                if isinstance(rm_r, str) and rm_r.strip():
                    bid = rm_r.strip()
                    book["reading_bookmarks"] = [x for x in _list(book, "reading_bookmarks") if x.get("id") != bid]
                rm_l = body.get("remove_listening_bookmark_id")
                if isinstance(rm_l, str) and rm_l.strip():
                    bid = rm_l.strip()
                    book["listening_bookmarks"] = [x for x in _list(book, "listening_bookmarks") if x.get("id") != bid]

                an = body.get("add_note")
                if isinstance(an, dict):
                    raw_t = an.get("text")
                    if isinstance(raw_t, str) and raw_t.strip():
                        tid = str(uuid.uuid4())
                        text = raw_t.strip()[:16000]
                        _list(book, "notes").append({"id": tid, "text": text, "created_at": now, "updated_at": now})

                rn = body.get("remove_note_id")
                if isinstance(rn, str) and rn.strip():
                    nid = rn.strip()
                    book["notes"] = [x for x in _list(book, "notes") if x.get("id") != nid]

                un = body.get("update_note")
                if isinstance(un, dict):
                    nid = un.get("id")
                    raw_t = un.get("text")
                    if isinstance(nid, str) and isinstance(raw_t, str) and raw_t.strip():
                        for n in _list(book, "notes"):
                            if n.get("id") == nid:
                                n["text"] = raw_t.strip()[:16000]
                                n["updated_at"] = now
                                break

                book["opened_at"] = now
                write_catalog(root, catalog)
                updated = self._library_public_book(book)
            self._send_json({"book": updated})
            return

        if parsed.path == "/api/settings":
            body = self._read_json_body()
            if not body:
                self._send_json({"error": "invalid json"}, status=400)
                return
            with _settings_lock:
                merged = merge_app_settings(read_app_settings(root), body)
                write_app_settings(root, merged)
            self._send_json({"settings": merged})
            return

        if parsed.path == "/api/library/start":
            body = self._read_json_body()
            if not body:
                self._send_json({"error": "invalid json"}, status=400)
                return
            book_id = body.get("id")
            if not book_id:
                self._send_json({"error": "missing id"}, status=400)
                return
            script = root / "epub_to_audiobook.py"
            if not script.is_file():
                self._send_json({"error": "epub_to_audiobook.py not found"}, status=500)
                return
            with _catalog_lock:
                catalog = read_catalog(root)
                book = next((b for b in catalog.get("books", []) if b.get("id") == book_id), None)
                if not book:
                    self._send_json({"error": "book not found"}, status=404)
                    return
                procs = parse_processes()
                st = compute_book_conversion_state(root, book, procs)["conversion_status"]
                if st in ("running", "starting"):
                    self._send_json({"error": "conversion already in progress", "book": self._library_public_book(book, active_processes=procs)}, status=409)
                    return
                if st == "ready":
                    self._send_json({"error": "audiobook already complete for this book", "book": self._library_public_book(book)}, status=409)
                    return
                epub_abs = (root / book["epub_rel_path"]).resolve()
                if not epub_abs.is_file():
                    self._send_json({"error": "epub file missing"}, status=400)
                    return
                outdir = root / "library" / "runs" / book_id
                outdir.mkdir(parents=True, exist_ok=True)
                slug = slugify_title(book["title"])
                book["run_relpath"] = str(Path("library/runs") / book_id / slug)
                book["last_error"] = None
                log_path = outdir / "conversion.log"
                write_catalog(root, catalog)

            app_settings = read_app_settings(root)
            mode = "hls-tts"
            kok_workers = 2
            kok_voice = str(app_settings.get("kokoro_voice") or "af_heart").strip() or "af_heart"
            rewrite_policy = LIBRARY_REWRITE_POLICY

            py_exe = resolve_library_pipeline_python(root)
            child_env = library_conversion_subprocess_env(root)
            cmd = [
                py_exe,
                str(script),
                str(epub_abs),
                "--outdir",
                str(outdir),
                "--tts-engine",
                "kokoro",
                "--mode",
                mode,
                "--kokoro-voice",
                kok_voice,
                "--kokoro-workers",
                str(kok_workers),
                "--rewrite-policy",
                rewrite_policy,
            ]
            # app_settings["output_retention"] is not passed through: the pipeline has no retention hook yet.
            try:
                logf = open(log_path, "ab")
            except OSError as e:
                self._send_json({"error": f"log file: {e}"}, status=500)
                return
            try:
                logf.write(f"[launch] python={py_exe}\n".encode("utf-8"))
                logf.flush()
                subprocess.Popen(
                    cmd,
                    cwd=str(root),
                    stdout=logf,
                    stderr=subprocess.STDOUT,
                    start_new_session=True,
                    env=child_env,
                )
            except OSError as e:
                logf.close()
                self._send_json({"error": str(e)}, status=500)
                return
            else:
                logf.close()

            catalog = read_catalog(root)
            book_rec = next((b for b in catalog.get("books", []) if b.get("id") == book_id), None)
            pub = self._library_public_book(dict(book_rec)) if book_rec else {}
            payload = merge_run_into_book(root, pub)
            self._send_json({"ok": True, "book": payload})
            return

        if parsed.path == "/api/library/stop":
            body = self._read_json_body()
            if not body:
                self._send_json({"error": "invalid json"}, status=400)
                return
            book_id = body.get("id")
            if not book_id:
                self._send_json({"error": "missing id"}, status=400)
                return
            catalog = read_catalog(root)
            book = next((b for b in catalog.get("books", []) if b.get("id") == book_id), None)
            if not book:
                self._send_json({"error": "book not found"}, status=404)
                return
            stop_info = stop_library_book_generation(root, book)
            payload = self._library_public_book(dict(book), active_processes=[])
            payload["conversion_status"] = "stopped"
            payload["generation_is_live"] = False
            self._send_json({"ok": True, "book": payload, **stop_info})
            return

        if parsed.path == "/api/library/pause":
            body = self._read_json_body()
            if not body:
                self._send_json({"error": "invalid json"}, status=400)
                return
            book_id = body.get("id")
            if not book_id:
                self._send_json({"error": "missing id"}, status=400)
                return
            catalog = read_catalog(root)
            book = next((b for b in catalog.get("books", []) if b.get("id") == book_id), None)
            if not book:
                self._send_json({"error": "book not found"}, status=404)
                return
            root_res = root.resolve()
            run_dir: Path | None = None
            rel = book.get("run_relpath")
            if isinstance(rel, str) and rel:
                try:
                    candidate = (root / rel).resolve()
                    candidate.relative_to(root_res)
                    run_dir = candidate
                except (OSError, ValueError):
                    run_dir = None
            outdir = _library_run_outdir(root, book)
            paused_pids = pause_library_run_processes(parse_processes(), run_dir, outdir)
            payload = self._library_public_book(dict(book), active_processes=[])
            payload["conversion_status"] = "paused"
            payload["generation_is_live"] = False
            self._send_json({"ok": True, "book": payload, "paused_pids": paused_pids, "paused": bool(paused_pids)})
            return

        if parsed.path == "/api/library/resume":
            body = self._read_json_body()
            if not body:
                self._send_json({"error": "invalid json"}, status=400)
                return
            book_id = body.get("id")
            if not book_id:
                self._send_json({"error": "missing id"}, status=400)
                return
            catalog = read_catalog(root)
            book = next((b for b in catalog.get("books", []) if b.get("id") == book_id), None)
            if not book:
                self._send_json({"error": "book not found"}, status=404)
                return
            root_res = root.resolve()
            run_dir: Path | None = None
            rel = book.get("run_relpath")
            if isinstance(rel, str) and rel:
                try:
                    candidate = (root / rel).resolve()
                    candidate.relative_to(root_res)
                    run_dir = candidate
                except (OSError, ValueError):
                    run_dir = None
            outdir = _library_run_outdir(root, book)
            resumed_pids = resume_library_run_processes(parse_processes(), run_dir, outdir)
            payload = self._library_public_book(dict(book), active_processes=[])
            payload["conversion_status"] = "running"
            payload["generation_is_live"] = True
            self._send_json({"ok": True, "book": payload, "resumed_pids": resumed_pids, "resumed": bool(resumed_pids)})
            return

        if parsed.path == "/api/library/delete":
            body = self._read_json_body()
            if not body:
                self._send_json({"error": "invalid json"}, status=400)
                return
            book_id = body.get("id")
            if not book_id:
                self._send_json({"error": "missing id"}, status=400)
                return
            payload = remove_library_book(root, str(book_id))
            self._send_json(payload)
            return

        self._send_json({"error": f"unknown POST path: {parsed.path}"}, status=404)

    def log_message(self, format: str, *args) -> None:  # noqa: A003
        return


def main() -> int:
    parser = argparse.ArgumentParser(description="Serve the Audiobook Library web app and pipeline monitor APIs.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8123)
    parser.add_argument("--root", type=Path, default=ROOT)
    args = parser.parse_args()

    Handler.root = args.root.resolve()
    server = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"Serving dashboard on http://{args.host}:{args.port} (root={Handler.root})", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
