"""JSON-backed background indexing job state for Book Chat."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def job_path_for_book(root: Path, book_id: str) -> Path:
    return root / "library" / "book_chat" / book_id / "index_job.json"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def default_job_status(root: Path, book_id: str) -> dict[str, Any]:
    return {
        "ok": True,
        "book_id": book_id,
        "status": "idle",
        "stage": "idle",
        "message": "",
        "current": 0,
        "total": 0,
        "percent": 0,
        "started_at": None,
        "updated_at": None,
        "error": None,
    }


def _compute_percent(current: int, total: int) -> int:
    if total <= 0:
        return 0
    return min(100, int(current * 100 / total))


def read_index_job(root: Path, book_id: str) -> dict[str, Any]:
    path = job_path_for_book(root, book_id)
    if not path.is_file():
        return default_job_status(root, book_id)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return default_job_status(root, book_id)
    if not isinstance(data, dict):
        return default_job_status(root, book_id)
    base = default_job_status(root, book_id)
    base.update(data)
    base["book_id"] = book_id
    base["ok"] = True
    return base


def write_index_job(root: Path, book_id: str, status_dict: dict[str, Any]) -> dict[str, Any]:
    path = job_path_for_book(root, book_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(status_dict)
    payload["ok"] = True
    payload["book_id"] = book_id
    now = _utc_now()
    if payload.get("started_at") is None and payload.get("status") == "running":
        payload["started_at"] = now
    payload["updated_at"] = now
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)
    return payload


def update_index_job(root: Path, book_id: str, **fields: Any) -> dict[str, Any]:
    current = read_index_job(root, book_id)
    current.update(fields)
    current["book_id"] = book_id
    if "current" in fields or "total" in fields:
        current["percent"] = _compute_percent(
            int(current.get("current") or 0),
            int(current.get("total") or 0),
        )
    return write_index_job(root, book_id, current)


def complete_index_job(
    root: Path,
    book_id: str,
    passage_count: int,
    embedding_model: str,
) -> dict[str, Any]:
    count = max(0, int(passage_count))
    model = (embedding_model or "").strip() or "unknown"
    message = f"Passage index ready ({count} passages)"
    return write_index_job(
        root,
        book_id,
        {
            "status": "done",
            "stage": "complete",
            "message": message,
            "current": count,
            "total": count,
            "percent": 100,
            "passage_count": count,
            "embedding_model": model,
            "error": None,
        },
    )


def fail_index_job(root: Path, book_id: str, error: str) -> dict[str, Any]:
    msg = str(error).strip() or "Indexing failed"
    return write_index_job(
        root,
        book_id,
        {
            "status": "error",
            "stage": "error",
            "message": msg,
            "error": msg,
        },
    )
