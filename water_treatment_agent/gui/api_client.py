"""Thin HTTP client wrapping the Water Treatment Agent FastAPI backend."""
from __future__ import annotations

import httpx

_TIMEOUT_HEALTH = 10.0
_TIMEOUT_RECOMMEND = 120.0   # LLM pipeline can take ~30-60 s
_TIMEOUT_INGEST = 30.0


def _url(base: str, path: str) -> str:
    return base.rstrip("/") + path


def get_health(base_url: str) -> dict:
    r = httpx.get(_url(base_url, "/health"), timeout=_TIMEOUT_HEALTH)
    r.raise_for_status()
    return r.json()


def post_recommend(payload: dict, base_url: str) -> dict:
    r = httpx.post(_url(base_url, "/recommend"), json=payload, timeout=_TIMEOUT_RECOMMEND)
    r.raise_for_status()
    return r.json()


def post_ingest(kb_type: str, data: dict, base_url: str) -> dict:
    r = httpx.post(
        _url(base_url, "/ingest"),
        json={"kb_type": kb_type, "data": data},
        timeout=_TIMEOUT_INGEST,
    )
    r.raise_for_status()
    return r.json()
