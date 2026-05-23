"""Tests for book_chat index job JSON persistence."""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from book_chat.index_job import (
    complete_index_job,
    default_job_status,
    fail_index_job,
    job_path_for_book,
    read_index_job,
    update_index_job,
    write_index_job,
)


@pytest.fixture
def workspace() -> Path:
    with TemporaryDirectory() as td:
        yield Path(td).resolve()


def test_default_job_status_is_idle_with_zero_percent(workspace: Path) -> None:
    status = default_job_status(workspace, "book-1")
    assert status["ok"] is True
    assert status["book_id"] == "book-1"
    assert status["status"] == "idle"
    assert status["stage"] == "idle"
    assert status["percent"] == 0
    assert status["current"] == 0
    assert status["total"] == 0
    assert status["error"] is None


def test_write_read_round_trip(workspace: Path) -> None:
    payload = default_job_status(workspace, "book-1")
    payload.update(
        {
            "status": "running",
            "stage": "embedding",
            "message": "Embedding passages 2 / 5",
            "current": 2,
            "total": 5,
            "percent": 40,
        }
    )
    write_index_job(workspace, "book-1", payload)
    path = job_path_for_book(workspace, "book-1")
    assert path.is_file()
    loaded = read_index_job(workspace, "book-1")
    assert loaded["status"] == "running"
    assert loaded["stage"] == "embedding"
    assert loaded["current"] == 2
    assert loaded["total"] == 5
    assert loaded["percent"] == 40


def test_update_computes_percent_and_preserves_book_id(workspace: Path) -> None:
    write_index_job(
        workspace,
        "book-1",
        {
            **default_job_status(workspace, "book-1"),
            "status": "running",
            "stage": "embedding",
            "current": 0,
            "total": 4,
        },
    )
    updated = update_index_job(
        workspace,
        "book-1",
        current=2,
        total=4,
        message="Embedding passages 2 / 4",
    )
    assert updated["book_id"] == "book-1"
    assert updated["current"] == 2
    assert updated["total"] == 4
    assert updated["percent"] == 50


def test_complete_status_is_done_at_one_hundred(workspace: Path) -> None:
    done = complete_index_job(workspace, "book-1", passage_count=7, embedding_model="fake-model")
    assert done["status"] == "done"
    assert done["stage"] == "complete"
    assert done["percent"] == 100
    assert done["current"] == 7
    assert done["total"] == 7
    assert "7" in done["message"]
    assert done["error"] is None
    reloaded = read_index_job(workspace, "book-1")
    assert reloaded["status"] == "done"
    assert reloaded["percent"] == 100


def test_fail_status_records_error(workspace: Path) -> None:
    failed = fail_index_job(workspace, "book-1", "extraction failed")
    assert failed["status"] == "error"
    assert failed["stage"] == "error"
    assert failed["error"] == "extraction failed"
    assert "extraction failed" in failed["message"]
    reloaded = read_index_job(workspace, "book-1")
    assert reloaded["status"] == "error"
