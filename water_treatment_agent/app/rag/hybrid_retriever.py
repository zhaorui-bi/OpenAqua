"""
Hybrid Retriever
----------------
Combines BM25 (keyword) and overlap-based semantic scoring over the
pre-built corpus, then merges results into a RetrievalBundle.

Retrieval flow
--------------
1. Load corpus.jsonl + BM25 index from index_dir (auto-build if missing).
2. For a given query, compute:
   - bm25_score   : BM25Okapi score for each corpus chunk
   - overlap_score: Jaccard-style token overlap (proxy for embedding similarity)
3. Combined score = bm25_weight * norm(bm25) + embedding_weight * overlap
4. Filter by kb_type, take top-k per KB, return RetrievalBundle.
"""
from __future__ import annotations

import json
import pickle
import re
from typing import List

from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.schemas import NormalizedQuery, RetrievalBundle, RetrievedChunk

logger = get_logger(__name__)


def _tokenize(text: str) -> List[str]:
    """Same tokenizer as IndexBuilder — must stay consistent."""
    return re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())


def _overlap_score(query_tokens: set, doc_tokens: set) -> float:
    """Jaccard similarity as a lightweight semantic proxy."""
    if not query_tokens or not doc_tokens:
        return 0.0
    return len(query_tokens & doc_tokens) / len(query_tokens | doc_tokens)


def _normalize_scores(scores: List[float]) -> List[float]:
    """Min-max normalize a list of scores to [0, 1]."""
    if not scores:
        return scores
    lo, hi = min(scores), max(scores)
    if hi == lo:
        return [1.0 if s > 0 else 0.0 for s in scores]
    return [(s - lo) / (hi - lo) for s in scores]


class HybridRetriever:
    """
    BM25 + overlap hybrid retriever over the pre-built JSON corpus.

    Indexes are built lazily on first query if not already present.
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._bm25 = None
        self._corpus: List[dict] = []
        self._loaded = False


    def retrieve(self, query: NormalizedQuery) -> RetrievalBundle:
        """
        Retrieve relevant chunks for *query* from kb_unit and kb_case KBs.

        Returns
        -------
        RetrievalBundle with kb_unit and kb_case lists.
        """
        if not self._loaded:
            self._load_or_build()

        query_text = self._build_query_text(query)
        query_tokens = set(_tokenize(query_text))

        scored_chunks = self._score_all(query_text, query_tokens)

        top_k = self._settings.top_k_rerank
        unit = self._top_k_by_type(scored_chunks, "kb_unit", top_k)
        case = self._top_k_by_type(scored_chunks, "kb_case", top_k)

        total = len(unit) + len(case)
        logger.info(
            "HybridRetriever: unit=%d case=%d (query=%r)",
            len(unit), len(case), query_text[:60],
        )
        return RetrievalBundle(
            query_id=query.query_id,
            kb_unit=unit,
            kb_case=case,
            total_retrieved=total,
        )

    def _load_or_build(self) -> None:
        """Load indexes from disk; auto-build if missing."""
        index_dir = self._settings.index_dir
        corpus_path = index_dir / "corpus.jsonl"
        bm25_path = index_dir / "bm25_index.pkl"

        if not corpus_path.exists() or not bm25_path.exists():
            logger.warning("HybridRetriever: indexes not found — building now")
            from app.rag.index_builder import IndexBuilder
            IndexBuilder().build_all()

        logger.info("HybridRetriever: loading corpus from %s", corpus_path)
        self._corpus = []
        with open(corpus_path, "r", encoding="utf-8") as f:
            for line in f:
                self._corpus.append(json.loads(line))

        with open(bm25_path, "rb") as f:
            self._bm25 = pickle.load(f)

        self._loaded = True
        logger.info("HybridRetriever: loaded %d chunks", len(self._corpus))



    def _build_query_text(self, query: NormalizedQuery) -> str:
        """Build a flat query string from all relevant fields."""
        parts: List[str] = []
        if query.source_water and query.source_water != "unknown":
            parts.append(query.source_water)
        parts.extend(query.contaminants)
        if query.context:
            parts.append(query.context)
        # Add contaminant synonyms to expand BM25 recall
        from app.core.taxonomy import get_taxonomy
        for c in query.contaminants:
            entry = get_taxonomy().get_contaminant(c)
            if entry:
                parts.extend(entry.get("synonyms", [])[:3])
        return " ".join(parts)

    def _score_all(
        self, query_text: str, query_tokens: set
    ) -> List[RetrievedChunk]:
        """Score every corpus chunk and return as RetrievedChunk list."""
        if not self._corpus or self._bm25 is None:
            return []

        q_tokens = _tokenize(query_text)

        # BM25 raw scores (unnormalized)
        bm25_raw = list(self._bm25.get_scores(q_tokens))
        bm25_norm = _normalize_scores(bm25_raw)

        # Overlap scores — already in [0,1]
        chunk_token_sets = [set(_tokenize(c["text"])) for c in self._corpus]
        overlap_scores = [_overlap_score(query_tokens, ct) for ct in chunk_token_sets]

        w_bm25 = self._settings.bm25_weight
        w_emb = self._settings.embedding_weight

        results: List[RetrievedChunk] = []
        for i, chunk in enumerate(self._corpus):
            combined = w_bm25 * bm25_norm[i] + w_emb * overlap_scores[i]
            results.append(
                RetrievedChunk(
                    source_id=chunk["source_id"],
                    chunk_id=chunk["chunk_id"],
                    relevance_score=round(combined, 4),
                    bm25_score=round(bm25_norm[i], 4),
                    embedding_score=round(overlap_scores[i], 4),
                    coverage_tags=chunk.get("coverage_tags", []),
                    text=chunk["text"],
                    # Merge kb_type (top-level in corpus) into metadata so
                    # _top_k_by_type() can filter on metadata.get("kb_type").
                    metadata={
                        **(chunk.get("metadata") or {}),
                        "kb_type": chunk.get("kb_type", "kb_unit"),
                    },
                )
            )

        return results

    def _top_k_by_type(
        self,
        chunks: List[RetrievedChunk],
        kb_type: str,
        top_k: int,
    ) -> List[RetrievedChunk]:
        """Filter chunks by kb_type (stored in metadata), sort desc, return top-k."""
        filtered = [
            c for c in chunks
            if c.metadata.get("kb_type") == kb_type
        ]
        filtered.sort(key=lambda c: c.relevance_score, reverse=True)
        return filtered[:top_k]
