"""
Evidence Binding
----------------
Associates retrieved chunks with specific claims in a candidate chain.

Matching strategy
-----------------
1. Primary filter : chunks where coverage_tags ∩ query_contaminants is non-empty
2. Boost          : chunks whose text mentions at least one key_unit name
3. Sort by combined relevance; return top max_citations

Each citation carries a human-readable claim describing what the evidence supports.
"""
from __future__ import annotations

from typing import List, Set

from app.core.schemas import CandidateChain, EvidenceCitation, NormalizedQuery, RetrievalBundle


def bind_evidence(
    chain: CandidateChain,
    retrieval: RetrievalBundle,
    query: NormalizedQuery | None = None,
    max_citations: int = 5,
) -> List[EvidenceCitation]:
    """
    Bind the most relevant retrieved chunks to a candidate chain.

    Parameters
    ----------
    chain :          CandidateChain to annotate.
    retrieval :      RetrievalBundle (all three KBs).
    query :          NormalizedQuery for contaminant-tag matching.
    max_citations :  Maximum citations to return.

    Returns
    -------
    List of EvidenceCitation sorted by combined score (descending).
    """
    query_contaminants: Set[str] = set(getattr(query, "contaminants", None) or [])
    key_units: Set[str] = set(chain.key_units or chain.chain[:2])

    all_chunks = retrieval.kb_unit + retrieval.kb_case

    scored: List[tuple[float, object]] = []
    for chunk in all_chunks:
        tag_set: Set[str] = set(chunk.coverage_tags)

        # Primary filter: must share at least one contaminant tag with the query
        contaminant_overlap = len(tag_set & query_contaminants) if query_contaminants else 1
        if query_contaminants and contaminant_overlap == 0:
            continue

        # Boost when key unit names appear literally in the chunk text
        text_lower = chunk.text.lower()
        unit_mentions = sum(1 for u in key_units if u.replace("_", " ") in text_lower)

        combined = chunk.relevance_score + contaminant_overlap * 0.1 + unit_mentions * 0.15
        scored.append((combined, chunk))

    scored.sort(key=lambda x: x[0], reverse=True)

    citations: List[EvidenceCitation] = []
    for _, chunk in scored[:max_citations]:
        claim = _generate_claim(chunk, chain, query_contaminants)
        support_type = "evidence_backed" if chunk.relevance_score > 0.3 else "system_inference"
        citations.append(
            EvidenceCitation(
                chunk_id=chunk.chunk_id,
                source_id=chunk.source_id,
                claim=claim,
                support_type=support_type,
                text_excerpt=chunk.text[:250].strip(),
            )
        )

    return citations


def _generate_claim(chunk, chain: CandidateChain, query_contaminants: Set[str]) -> str:
    """Build a human-readable claim string from chunk metadata and chain context."""
    tags = set(chunk.coverage_tags) & query_contaminants
    target = ", ".join(sorted(tags)) if tags else "target contaminants"

    # New source_id format: "treatment_{Contaminant}_{Function_slug}"
    # metadata["function"] carries the human-readable function name.
    if chunk.source_id.startswith("treatment_"):
        func = chunk.metadata.get("function", "") if chunk.metadata else ""
        if func and func.lower() != "overall":
            return f"{func} effectiveness for {target} removal"
        return f"Treatment effectiveness for {target} removal"

    # New source_id format: "tdb_{Contaminant}_{subtype}"
    if chunk.source_id.startswith("tdb_"):
        subtype = chunk.metadata.get("subtype", "") if chunk.metadata else ""
        if subtype == "properties":
            return f"Physicochemical properties of {target} relevant to treatment selection"
        if subtype == "fatetrans":
            return f"Fate and transport of {target} through treatment processes"
        if subtype == "ref":
            return f"Literature evidence for {target} treatment methods"
        if subtype == "description":
            return f"Background and regulatory context for {target}"
        return f"Technical data for {target}"

    if chunk.source_id == "kb_cases":
        title = chunk.metadata.get("title", "case study")
        return f"Real-world case: {title}"

    key = ", ".join(sorted(set(chain.key_units[:2])))
    return f"Supporting evidence for {key} treating {target}"
