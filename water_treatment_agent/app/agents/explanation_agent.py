"""
Explanation Agent
-----------------
Generates the final FinalReport with per-chain structured explanations.

For each passing chain:
  1. bind_evidence()         — select the most relevant evidence citations
  2. compute_rank_score()    — produce decomposed interpretable score
  3. _explain_chain()        — LLM generates why_it_works / risks / assumptions
                                (falls back to template text when LLM unavailable)

Evidence citation rule: if fewer than 2 evidence_backed citations exist for a
chain, the uncertainty level is elevated and the explanation notes
"Insufficient evidence" for unsubstantiated claims.
"""
from __future__ import annotations

import json
from typing import List, Optional

from openai import OpenAI

from app.agents.prompts import EXPLANATION_SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.schemas import (
    CandidateChain,
    CandidatesBundle,
    ChainConstraintReport,
    CheckStatus,
    ConstraintReport,
    EvidenceCitation,
    FinalReport,
    NormalizedQuery,
    RecommendationItem,
    RetrievalBundle,
    UncertaintyLevel,
)
from app.utils.evidence_binding import bind_evidence
from app.utils.scoring import compute_rank_score

logger = get_logger(__name__)


class ExplanationAgent:
    """
    Assembles the final FinalReport from all upstream agent outputs.

    Usage::

        agent = ExplanationAgent()
        report = agent.run(query, candidates, retrieval, constraint_report)
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._llm: Optional[OpenAI] = None
        if self._settings.openrouter_api_key:
            self._llm = OpenAI(
                api_key=self._settings.openrouter_api_key,
                base_url=self._settings.openrouter_base_url,
            )
        else:
            logger.warning(
                "ExplanationAgent: OPENROUTER_API_KEY not set — using template-based explanations"
            )

    def run(
        self,
        query: NormalizedQuery,
        candidates: CandidatesBundle,
        retrieval: RetrievalBundle,
        constraint_report: ConstraintReport,
        top_k: int = 3,
    ) -> FinalReport:
        """
        Build FinalReport with ranked, evidence-bound recommendations.

        Parameters
        ----------
        query :             NormalizedQuery
        candidates :        CandidatesBundle (chains may have been revised by Critic)
        retrieval :         RetrievalBundle
        constraint_report : ConstraintReport (per-chain check results)
        top_k :             Max recommendations to include.

        Returns
        -------
        FinalReport
        """
        logger.info("ExplanationAgent: building report for query %s", query.query_id)

        constraint_map = {r.chain_id: r for r in constraint_report.chain_reports}
        recommendations: List[RecommendationItem] = []

        for chain in candidates.candidates:
            chain_cr = constraint_map.get(chain.chain_id)

            # Skip chains that fully failed (even after auto-revision)
            if chain_cr and chain_cr.overall_status == CheckStatus.FAIL:
                logger.debug("ExplanationAgent: skipping dropped chain %s", chain.chain_id)
                continue

            # ── Evidence binding ──
            evidence = bind_evidence(chain, retrieval, query=query, max_citations=5)

            # ── Ranking score ──
            score = compute_rank_score(chain, query, retrieval, chain_cr)

            # ── Uncertainty level ──
            uncertainty = self._assess_uncertainty(evidence)

            # ── LLM / template explanation ──
            why, risks, assumptions = self._explain_chain(chain, query, evidence, chain_cr)

            # Merge query-level assumptions (deduplicated)
            merged_assumptions = list(dict.fromkeys(assumptions + (query.assumptions or [])))

            # ── Fallback constraint report (NA) when none available ──
            if chain_cr is None:
                chain_cr = ChainConstraintReport(
                    chain_id=chain.chain_id,
                    overall_status=CheckStatus.NA,
                    checks=[],
                )

            recommendations.append(
                RecommendationItem(
                    rank=0,  # assigned after sort
                    chain_id=chain.chain_id,
                    chain=chain.chain,
                    rank_score=score,
                    why_it_works=why,
                    evidence=evidence,
                    assumptions=merged_assumptions,
                    risks=risks,
                    retrieved_cases=[c.chunk_id for c in retrieval.kb_case[:2]],
                    constraint_report=chain_cr,
                    uncertainty=uncertainty,
                )
            )

        # Sort by total score, assign ranks
        recommendations.sort(key=lambda r: r.rank_score.total, reverse=True)
        for i, rec in enumerate(recommendations[:top_k], start=1):
            rec.rank = i

        system_notes: List[str] = []
        if not self._llm:
            system_notes.append(
                "Explanations generated by template (no LLM). "
                "Set OPENROUTER_API_KEY for LLM-generated explanations."
            )

        logger.info(
            "ExplanationAgent: returning %d recommendations", min(top_k, len(recommendations))
        )
        return FinalReport(
            query_id=query.query_id,
            normalized_query=query,
            recommendations=recommendations[:top_k],
            system_notes=system_notes,
        )

    def _explain_chain(
        self,
        chain: CandidateChain,
        query: NormalizedQuery,
        evidence: List[EvidenceCitation],
        chain_cr: Optional[ChainConstraintReport],
    ) -> tuple[str, List[str], List[str]]:
        """Return (why_it_works, risks, assumptions). Tries LLM first."""
        if self._llm:
            result = self._call_llm(chain, query, evidence, chain_cr)
            if result:
                return result
        return self._template_explanation(chain, query, evidence)

    def _call_llm(
        self,
        chain: CandidateChain,
        query: NormalizedQuery,
        evidence: List[EvidenceCitation],
        chain_cr: Optional[ChainConstraintReport],
    ) -> Optional[tuple[str, List[str], List[str]]]:
        """Call LLM to generate structured explanation. Returns None on failure."""
        try:
            evidence_text = "\n".join(
                f"[{e.source_id}] ({e.support_type}) {e.text_excerpt}"
                for e in evidence
            ) or "No relevant evidence retrieved."

            if chain_cr:
                passes = [c.rule_id for c in chain_cr.checks if c.status == CheckStatus.PASS]
                warns  = [c.rule_id for c in chain_cr.checks if c.status == CheckStatus.WARN]
                cr_summary = f"Passed: {passes}. Warnings: {warns}."
            else:
                cr_summary = "No constraint check performed."

            constraints = {}
            if query.constraints:
                constraints = query.constraints.model_dump(exclude_none=True, exclude={"extra"})

            prompt = EXPLANATION_SYSTEM_PROMPT.format(
                chain=" → ".join(chain.chain),
                contaminants=query.contaminants,
                constraints=constraints or "none",
                evidence_text=evidence_text,
                constraint_summary=cr_summary,
            )

            response = self._llm.chat.completions.create(
                model=self._settings.explanation_model,
                temperature=self._settings.llm_temperature,
                max_tokens=self._settings.llm_max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = (response.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw)
            return (
                parsed.get("why_it_works") or chain.rationale,
                parsed.get("risks") or [],
                parsed.get("assumptions") or [],
            )
        except json.JSONDecodeError as e:
            logger.warning("ExplanationAgent: LLM returned invalid JSON — %s", e)
        except Exception as e:
            logger.warning("ExplanationAgent: LLM call failed — %s", e)
        return None

    def _template_explanation(
        self,
        chain: CandidateChain,
        query: NormalizedQuery,
        evidence: List[EvidenceCitation],
    ) -> tuple[str, List[str], List[str]]:
        """Build evidence-grounded explanation without LLM."""
        backed = [e for e in evidence if e.support_type == "evidence_backed"]
        evidence_refs = " ".join(f"[{e.source_id}]" for e in backed)

        if backed:
            excerpt = backed[0].text_excerpt[:200]
            why = (
                f"{chain.rationale} "
                f"Supported by retrieved evidence {evidence_refs}: \"{excerpt}...\""
            )
        else:
            why = (
                f"{chain.rationale} "
                "Insufficient evidence retrieved to substantiate this recommendation — "
                "verify against primary literature before implementation."
            )

        risks: List[str] = []
        if chain.generates_brine:
            risks.append("Generates concentrate brine — ensure a safe disposal route is in place.")
        if chain.energy_intensity and chain.energy_intensity.value in ("high", "medium-high"):
            risks.append("High energy consumption; assess grid reliability and operating cost.")
        if len(chain.chain) > 5:
            risks.append("Multi-step chain increases operational complexity and maintenance burden.")
        if not risks:
            risks.append("Residuals (sludge, spent media) require periodic safe disposal.")

        assumptions: List[str] = [
            "Source water quality assumed to be as described; "
            "seasonal variation may affect performance.",
            "Adequate reagent supply (coagulant, disinfectant, etc.) assumed available on-site.",
        ]

        return why, risks, assumptions


    def _assess_uncertainty(self, evidence: List[EvidenceCitation]) -> UncertaintyLevel:
        """
        ≥3 evidence_backed citations → LOW
        1-2 evidence_backed citations → MEDIUM
        0 evidence_backed citations   → INSUFFICIENT_EVIDENCE
        """
        backed = sum(1 for e in evidence if e.support_type == "evidence_backed")
        if backed >= 3:
            return UncertaintyLevel.LOW
        if backed >= 1:
            return UncertaintyLevel.MEDIUM
        return UncertaintyLevel.INSUFFICIENT_EVIDENCE
