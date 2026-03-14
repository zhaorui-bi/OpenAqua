"""
Main pipeline orchestrator.
Chains the 5 agents in sequence with an optional critic-retry loop.
"""
from __future__ import annotations

from app.agents.critic_agent import ConstraintCriticAgent
from app.agents.explanation_agent import ExplanationAgent
from app.agents.parser_agent import TaskParserAgent
from app.agents.planner_agent import ProcessPlannerAgent
from app.agents.retrieval_agent import RetrievalAgent
from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.schemas import FinalReport, UserQuery

logger = get_logger(__name__)


class WaterTreatmentPipeline:
    """
    End-to-end pipeline: UserQuery → FinalReport.

    Usage::

        pipeline = WaterTreatmentPipeline()
        report = pipeline.run(user_query, top_k=3)
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._parser = TaskParserAgent()
        self._retriever = RetrievalAgent()
        self._planner = ProcessPlannerAgent()
        self._critic = ConstraintCriticAgent()
        self._explainer = ExplanationAgent()

    def run(self, query: UserQuery, top_k: int = 3) -> FinalReport:
        """
        Execute the full 5-agent pipeline.

        Parameters
        ----------
        query :  Raw user input.
        top_k :  Number of recommendations to return.

        Returns
        -------
        FinalReport
        """
        # Step 1 — Parse
        normalized = self._parser.run(query)
        logger.info("Pipeline step 1/5 done: parsed query %s", normalized.query_id)

        # Step 2 — Retrieve
        retrieval = self._retriever.run(normalized)
        logger.info("Pipeline step 2/5 done: retrieved %d chunks", retrieval.total_retrieved)

        # Step 3 — Plan
        candidates = self._planner.run(normalized, retrieval)
        logger.info("Pipeline step 3/5 done: %d candidates generated", len(candidates.candidates))

        # Step 4 — Critique (with optional retry loop)
        constraint_report = self._critic.run(candidates, normalized)
        logger.info(
            "Pipeline step 4/5 done: %d to revise, %d to drop",
            len(constraint_report.chains_to_revise),
            len(constraint_report.chains_to_drop),
        )

        # Optional retry: if critic dropped too many chains, re-plan once
        max_iter = self._settings.max_critic_iterations
        iteration = 0
        while (
            iteration < max_iter
            and len(constraint_report.chains_to_drop) >= len(candidates.candidates)
        ):
            logger.warning("Pipeline: all candidates dropped — replanning (iter %d)", iteration + 1)
            candidates = self._planner.run(normalized, retrieval)
            constraint_report = self._critic.run(candidates, normalized)
            iteration += 1

        # Step 5 — Explain
        report = self._explainer.run(normalized, candidates, retrieval, constraint_report, top_k=top_k)
        logger.info("Pipeline step 5/5 done: %d recommendations", len(report.recommendations))

        return report
