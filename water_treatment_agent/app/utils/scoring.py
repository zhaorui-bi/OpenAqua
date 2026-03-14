"""
Scoring module
--------------
Computes a decomposed, interpretable rank_score for each candidate chain.

Score components
----------------
coverage_score   : fraction of input contaminants/targets addressed by the chain
constraint_score : penalty-adjusted score based on constraint check results
evidence_score   : fraction of claims supported by retrieved evidence
risk_penalty     : negative term for high energy, brine, residuals, complexity
"""
from __future__ import annotations

from typing import Optional

from app.core.schemas import (
    CandidateChain,
    ChainConstraintReport,
    CheckStatus,
    NormalizedQuery,
    RankScore,
    RetrievalBundle,
)


def compute_rank_score(
    chain: CandidateChain,
    query: NormalizedQuery,
    retrieval: RetrievalBundle,
    constraint_report: Optional[ChainConstraintReport] = None,
) -> RankScore:
    """
    Compute the full RankScore for a candidate chain.

    Parameters
    ----------
    chain :              CandidateChain to score.
    query :              NormalizedQuery (provides contaminants, constraints).
    retrieval :          RetrievalBundle (used for evidence_score).
    constraint_report :  Optional per-chain constraint check result.

    Returns
    -------
    RankScore with all components filled.
    """
    coverage = _coverage_score(chain, query)
    constraint = _constraint_score(constraint_report)
    evidence = _evidence_score(chain, retrieval)
    risk = _risk_penalty(chain, query)

    total = max(0.0, min(1.0, coverage * 0.35 + constraint * 0.30 + evidence * 0.25 + risk))

    return RankScore(
        total=round(total, 4),
        coverage_score=round(coverage, 4),
        constraint_score=round(constraint, 4),
        evidence_score=round(evidence, 4),
        risk_penalty=round(risk, 4),
        score_breakdown={
            "coverage_weight": 0.35,
            "constraint_weight": 0.30,
            "evidence_weight": 0.25,
            "risk_weight": 1.0,
        },
    )



def _coverage_score(chain: CandidateChain, query: NormalizedQuery) -> float:
    """
    Fraction of input contaminants for which the chain contains at least
    one known-effective treatment unit, using the CONTAMINANT_UNIT_MAP
    imported from planner_agent.
    """
    if not query.contaminants:
        return 0.5  # neutral when no contaminants specified

    from app.agents.planner_agent import CONTAMINANT_UNIT_MAP

    chain_set = set(chain.chain)
    covered = 0
    for contaminant in query.contaminants:
        effective_units = set(CONTAMINANT_UNIT_MAP.get(contaminant.lower(), []))
        if chain_set & effective_units:
            covered += 1

    return covered / len(query.contaminants)


def _constraint_score(report: Optional[ChainConstraintReport]) -> float:
    """
    1.0 for PASS, 0.6 for WARN, 0.0 for FAIL, 0.8 if no report.
    Averaged across all checks.
    """
    if report is None:
        return 0.8

    scores = []
    for check in report.checks:
        if check.status == CheckStatus.PASS:
            scores.append(1.0)
        elif check.status == CheckStatus.WARN:
            scores.append(0.6)
        elif check.status == CheckStatus.FAIL:
            scores.append(0.0)
        # NA checks are ignored
    return sum(scores) / len(scores) if scores else 0.8


def _evidence_score(chain: CandidateChain, retrieval: RetrievalBundle) -> float:
    """
    Fraction of retrieved kb_unit chunks that are relevant to the chain's
    key units (unit name appears in chunk text) — a proxy for citation support.
    """
    if not retrieval.kb_unit:
        return 0.0

    key_units = set(chain.key_units or chain.chain[:2])
    matched = sum(
        1 for chunk in retrieval.kb_unit
        if any(u.replace("_", " ").lower() in chunk.text.lower() for u in key_units)
    )
    return min(1.0, matched / max(len(retrieval.kb_unit), 1))


def _risk_penalty(chain: CandidateChain, query: NormalizedQuery) -> float:
    """
    Negative penalty for high-risk factors.

    Factors
    -------
    - generates_brine without disposal: -0.20
    - high energy with limited energy constraint: -0.10
    - chain length > 6 (complexity): -0.05
    """
    penalty = 0.0
    c = query.constraints

    if chain.generates_brine and c and c.brine_disposal is False:
        penalty -= 0.20

    high_energy_units = {"Membrane Separation", "Membrane Filtration"}
    if c and c.energy == "limited" and any(u in high_energy_units for u in chain.chain):
        penalty -= 0.10

    if len(chain.chain) > 6:
        penalty -= 0.05

    return penalty
