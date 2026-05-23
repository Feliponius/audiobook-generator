"""Tests for book_chat JSONL passage index storage and retrieval."""

from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from book_chat.embeddings import FakeHashEmbedder
from book_chat.index_store import (
    cosine_similarity,
    index_path_for_book,
    read_passages,
    retrieve_top_k,
    write_passages,
)


def test_index_path_for_book_under_library_book_chat() -> None:
    root = Path("/data/repo")
    p = index_path_for_book(root, "book-abc")
    assert p == root / "library" / "book_chat" / "book-abc" / "passages.jsonl"


def test_write_and_read_passages_round_trip() -> None:
    with TemporaryDirectory() as td:
        path = Path(td) / "passages.jsonl"
        records = [
            {
                "id": "passage_b1_0",
                "book_id": "b1",
                "chapter": "Intro",
                "text": "First passage about discipline.",
                "embedding_model": "fake",
                "embedding": [1.0, 0.0],
            },
            {
                "id": "passage_b1_1",
                "book_id": "b1",
                "chapter": "Ch2",
                "text": "Second passage about rest.",
                "embedding_model": "fake",
                "embedding": [0.0, 1.0],
            },
        ]
        write_passages(path, records)
        loaded = read_passages(path)
        assert len(loaded) == 2
        assert loaded[0]["id"] == "passage_b1_0"
        assert loaded[1]["text"] == "Second passage about rest."


def test_read_passages_missing_file_returns_empty() -> None:
    with TemporaryDirectory() as td:
        path = Path(td) / "missing.jsonl"
        assert read_passages(path) == []


def test_cosine_similarity_orders_vectors() -> None:
    q = [1.0, 0.0]
    a = [1.0, 0.0]
    b = [0.0, 1.0]
    assert cosine_similarity(q, a) > cosine_similarity(q, b)


def test_retrieve_top_k_includes_passage_metadata_when_present() -> None:
    embedder = FakeHashEmbedder(dimension=8)
    passages = [
        {
            "id": "p0",
            "book_id": "b1",
            "chapter": "Chapter 5",
            "text": "discipline and habits",
            "source": "chapter_5.xhtml",
            "href": "chapter_5.xhtml",
            "chapter_index": 5,
            "chunk_index": 3,
            "embedding_model": embedder.model_name,
            "embedding": embedder.embed("discipline and habits"),
        },
    ]
    query_vec = embedder.embed("discipline")
    hits = retrieve_top_k(query_vec, passages, top_k=1)
    assert hits[0]["source"] == "chapter_5.xhtml"
    assert hits[0]["href"] == "chapter_5.xhtml"
    assert hits[0]["chapter_index"] == 5
    assert hits[0]["chunk_index"] == 3


def test_retrieve_top_k_returns_closest_passage() -> None:
    embedder = FakeHashEmbedder(dimension=8)
    passages = [
        {
            "id": "p0",
            "book_id": "b1",
            "chapter": "A",
            "text": "discipline and habits",
            "embedding_model": embedder.model_name,
            "embedding": embedder.embed("discipline and habits"),
        },
        {
            "id": "p1",
            "book_id": "b1",
            "chapter": "B",
            "text": "sleep and recovery",
            "embedding_model": embedder.model_name,
            "embedding": embedder.embed("sleep and recovery"),
        },
    ]
    query_vec = embedder.embed("building discipline through habits")
    hits = retrieve_top_k(query_vec, passages, top_k=1)
    assert len(hits) == 1
    assert hits[0]["passage_id"] == "p0"
    assert hits[0]["score"] > 0.5


def test_write_passages_creates_parent_dirs() -> None:
    with TemporaryDirectory() as td:
        path = Path(td) / "nested" / "dir" / "passages.jsonl"
        write_passages(path, [{"id": "x", "book_id": "b", "chapter": "", "text": "t", "embedding": [1.0]}])
        assert path.is_file()
        line = path.read_text(encoding="utf-8").strip()
        assert json.loads(line)["id"] == "x"
