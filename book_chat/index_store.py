"""JSONL passage index storage and cosine-similarity retrieval."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any


def index_path_for_book(root: Path, book_id: str) -> Path:
    return root / "library" / "book_chat" / book_id / "passages.jsonl"


def write_passages(path: Path, records: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".jsonl.tmp")
    lines = [json.dumps(rec, ensure_ascii=False) for rec in records]
    tmp.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
    tmp.replace(path)


def read_passages(path: Path) -> list[dict[str, Any]]:
    if not path.is_file():
        return []
    out: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            val = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(val, dict):
            out.append(val)
    return out


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    if na == 0.0 or nb == 0.0:
        return 0.0
    return dot / (na * nb)


def retrieve_top_k(
    query_embedding: list[float],
    passages: list[dict[str, Any]],
    *,
    top_k: int = 3,
) -> list[dict[str, Any]]:
    scored: list[tuple[float, dict[str, Any]]] = []
    for passage in passages:
        emb = passage.get("embedding")
        if not isinstance(emb, list) or not emb:
            continue
        try:
            vec = [float(x) for x in emb]
        except (TypeError, ValueError):
            continue
        score = cosine_similarity(query_embedding, vec)
        scored.append((score, passage))
    scored.sort(key=lambda item: item[0], reverse=True)
    hits: list[dict[str, Any]] = []
    for score, passage in scored[: max(top_k, 0)]:
        hits.append(
            {
                "passage_id": passage.get("id"),
                "score": round(score, 6),
                "chapter": passage.get("chapter") or "",
                "text": passage.get("text") or "",
                "snippet": _snippet(passage.get("text") or ""),
            }
        )
    return hits


def _snippet(text: str, limit: int = 240) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"
