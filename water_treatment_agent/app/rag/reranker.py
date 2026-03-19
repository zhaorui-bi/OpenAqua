"""
Reranker
--------
Merges BM25 and embedding scores using a weighted combination,
then sorts chunks by combined relevance.
"""
from __future__ import annotations

from typing import List

from app.core.config import get_settings
from app.core.schemas import RetrievedChunk


class Reranker:
    """Combines BM25 and embedding scores."""

    def __init__(self) -> None:
        self._settings = get_settings()

    def rerank(self, chunks: List[RetrievedChunk]) -> List[RetrievedChunk]:
        """
        Compute combined scores and return sorted chunks (descending).

        Parameters
        ----------
        chunks : list of RetrievedChunk with bm25_score and/or embedding_score set.
        """
        w_bm25 = self._settings.bm25_weight
        w_emb = self._settings.embedding_weight

        for chunk in chunks:
            bm25 = chunk.bm25_score or 0.0
            emb = chunk.embedding_score or 0.0
            chunk.relevance_score = w_bm25 * bm25 + w_emb * emb

        return sorted(chunks, key=lambda c: c.relevance_score, reverse=True)
