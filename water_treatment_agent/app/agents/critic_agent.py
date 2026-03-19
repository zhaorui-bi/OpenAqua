"""
Constraint / Critic Agent
--------------------------
Applies the rule library (rules.py) to each candidate chain and produces a
ConstraintReport.

Auto-revision
-------------
Before marking a chain as "to_drop", the critic attempts one automatic fix:
  R-002 FAIL (missing disinfection) → append "Chlorine"
  R-003 FAIL (Membrane Separation with no brine disposal) → replace with "Ion Exchange"

If the revised chain passes all hard rules, it is returned with overall=WARN
(flagged for human review) and moved to chains_to_revise instead of chains_to_drop.
If revision still fails, the chain is dropped.
"""
from __future__ import annotations

from copy import deepcopy
from typing import List

from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.rules import apply_rules
from app.core.schemas import (
    CandidateChain,
    CandidatesBundle,
    ChainConstraintReport,
    CheckStatus,
    ConstraintReport,
    NormalizedQuery,
    UnitCheckResult,
)

logger = get_logger(__name__)

# Real taxonomy unit names (Title Case)
_DISINFECTION_UNITS = {
    "Chlorine", "Chloramine", "Chlorine Dioxide",
    "Ozone", "Ozone and Hydrogen Peroxide",
    "Ultraviolet Irradiation",
    "Ultraviolet Irradiation and Hydrogen Peroxide",
    "Ultraviolet Irradiation and Ozone",
}
_BRINE_UNITS = {
    "Membrane Separation",
}

# The unit appended during auto-revision must be a real taxonomy name
_AUTO_DISINFECTION_UNIT = "Chlorine"
_AUTO_BRINE_REPLACEMENT = "Ion Exchange"


class ConstraintCriticAgent:
    """
    Evaluates all candidate chains against the rule library.

    Usage::

        agent = ConstraintCriticAgent()
        report = agent.run(candidates_bundle, normalized_query)
    """

    def __init__(self) -> None:
        self._settings = get_settings()

    def run(
        self,
        candidates: CandidatesBundle,
        query: NormalizedQuery,
    ) -> ConstraintReport:
        """
        Apply all registered rules to every candidate chain.

        Chains that fail hard rules get one auto-revision attempt.
        If revision succeeds → WARN + to_revise.
        If revision still fails → FAIL + to_drop.

        Returns
        -------
        ConstraintReport
        """
        logger.info(
            "ConstraintCriticAgent: checking %d candidates for query %s",
            len(candidates.candidates),
            query.query_id,
        )

        chain_reports: List[ChainConstraintReport] = []
        to_revise: List[str] = []
        to_drop: List[str] = []

        for chain in candidates.candidates:
            checks = apply_rules(chain, query)
            has_fail = any(c.status == CheckStatus.FAIL for c in checks)
            has_warn = any(c.status == CheckStatus.WARN for c in checks)

            if has_fail:
                # ── Attempt auto-revision before dropping ──
                revised, revision_log = self._try_auto_revise(chain, query)
                revised_checks = apply_rules(revised, query)
                still_fails = any(c.status == CheckStatus.FAIL for c in revised_checks)

                if still_fails:
                    overall = CheckStatus.FAIL
                    to_drop.append(chain.chain_id)
                    revision_actions = self._build_actions(checks) + revision_log
                    final_checks = checks
                else:
                    # Revision succeeded — mutate chain in place, mark as WARN
                    overall = CheckStatus.WARN
                    to_revise.append(chain.chain_id)
                    revision_actions = revision_log
                    final_checks = revised_checks
                    chain.chain = revised.chain
                    chain.key_units = revised.key_units
                    chain.generates_brine = revised.generates_brine
                    chain.requires_disinfection = revised.requires_disinfection
                    logger.info(
                        "ConstraintCriticAgent: auto-revised %s → %s",
                        chain.chain_id, chain.chain,
                    )

            elif has_warn:
                overall = CheckStatus.WARN
                to_revise.append(chain.chain_id)
                revision_actions = self._build_actions(checks)
                final_checks = checks
            else:
                overall = CheckStatus.PASS
                revision_actions = []
                final_checks = checks

            chain_reports.append(
                ChainConstraintReport(
                    chain_id=chain.chain_id,
                    overall_status=overall,
                    checks=final_checks,
                    revision_actions=revision_actions,
                )
            )

        logger.info(
            "ConstraintCriticAgent: PASS=%d WARN=%d DROP=%d",
            sum(1 for r in chain_reports if r.overall_status == CheckStatus.PASS),
            len(to_revise),
            len(to_drop),
        )
        return ConstraintReport(
            query_id=query.query_id,
            chain_reports=chain_reports,
            chains_to_revise=to_revise,
            chains_to_drop=to_drop,
        )

    def _try_auto_revise(
        self,
        chain: CandidateChain,
        query: NormalizedQuery,
    ) -> tuple[CandidateChain, List[str]]:
        """
        Attempt to repair a failing chain with targeted unit-level fixes.

        Returns a copy of *chain* with fixes applied and a log of changes.
        """
        revised = deepcopy(chain)
        log: List[str] = []

        # Pre-compute lower-cased sets for case-insensitive membership tests
        _disinfection_lower = {u.strip().replace("_", " ").lower() for u in _DISINFECTION_UNITS}
        _brine_lower = {u.strip().replace("_", " ").lower() for u in _BRINE_UNITS}

        # Fix R-002: append _AUTO_DISINFECTION_UNIT if disinfection required but absent
        for check in apply_rules(revised, query):
            if check.rule_id == "R-002" and check.status == CheckStatus.FAIL:
                chain_lower = {u.strip().replace("_", " ").lower() for u in revised.chain}
                if not (chain_lower & _disinfection_lower):
                    revised.chain.append(_AUTO_DISINFECTION_UNIT)
                    revised.requires_disinfection = True
                    log.append(
                        f"Auto-revision [R-002]: added '{_AUTO_DISINFECTION_UNIT}' as disinfection barrier"
                    )

        # Fix R-003: replace RO/NF with _AUTO_BRINE_REPLACEMENT when no brine disposal
        for check in apply_rules(revised, query):
            if check.rule_id == "R-003" and check.status == CheckStatus.FAIL:
                removed = [
                    u for u in revised.chain
                    if u.strip().replace("_", " ").lower() in _brine_lower
                ]
                if removed:
                    insert_pos = next(
                        (
                            i for i, u in enumerate(revised.chain)
                            if u.strip().replace("_", " ").lower() in _brine_lower
                        ),
                        -1,
                    )
                    revised.chain = [
                        u for u in revised.chain
                        if u.strip().replace("_", " ").lower() not in _brine_lower
                    ]
                    if _AUTO_BRINE_REPLACEMENT not in revised.chain:
                        revised.chain.insert(max(insert_pos, 0), _AUTO_BRINE_REPLACEMENT)
                    revised.generates_brine = False
                    log.append(
                        f"Auto-revision [R-003]: replaced {removed} with '{_AUTO_BRINE_REPLACEMENT}' "
                        f"(brine disposal unavailable)"
                    )

        return revised, log


    def _build_actions(self, checks: List[UnitCheckResult]) -> List[str]:
        """Collect FAIL/WARN check messages as revision action strings."""
        return [
            f"[{c.rule_id}] {c.message}"
            for c in checks
            if c.status in (CheckStatus.FAIL, CheckStatus.WARN)
        ]
