"""
Retrieval Agent
---------------
Queries the three knowledge bases (KB_unit, KB_template, KB_case) using
hybrid BM25 + embedding retrieval, then assembles a RetrievalBundle.
"""
from __future__ import annotations

from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.schemas import NormalizedQuery, RetrievalBundle
from app.rag.hybrid_retriever import HybridRetriever

logger = get_logger(__name__)

from app.agents.prompts import RETRIEVAL_SYSTEM_PROMPT  # noqa: E402  (future use)


class RetrievalAgent:
    """
    Wraps HybridRetriever and returns a unified RetrievalBundle.

    Usage::

        agent = RetrievalAgent()
        bundle = agent.run(normalized_query)
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._retriever = HybridRetriever()

    def run(self, query: NormalizedQuery) -> RetrievalBundle:
        """
        Retrieve evidence from all three KBs.

        Parameters
        ----------
        query : NormalizedQuery
            Parsed user query.

        Returns
        -------
        RetrievalBundle
            Chunks from KB_unit, KB_template, and KB_case.
        """
        logger.info("RetrievalAgent: retrieving for query %s", query.query_id)
        bundle = self._retriever.retrieve(query)
        logger.info(
            "RetrievalAgent: retrieved %d total chunks", bundle.total_retrieved
        )
        return bundle
