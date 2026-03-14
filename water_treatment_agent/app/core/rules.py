"""
Constraint rule library.  Rules are data-driven and configurable —
no business logic is hard-coded in agent files.

Each rule is a callable that receives a CandidateChain + NormalizedQuery
and returns a UnitCheckResult.
"""
from __future__ import annotations

from typing import Callable, Dict, List

from app.core.schemas import (
    CandidateChain,
    CheckStatus,
    NormalizedQuery,
    UnitCheckResult,
)
from app.core.taxonomy import get_taxonomy

# Type alias for a rule function
RuleFn = Callable[[CandidateChain, NormalizedQuery], UnitCheckResult]

# Registry: rule_id → RuleFn
_RULE_REGISTRY: Dict[str, RuleFn] = {}


def register_rule(rule_id: str) -> Callable[[RuleFn], RuleFn]:
    """Decorator to register a rule function by ID."""
    def decorator(fn: RuleFn) -> RuleFn:
        _RULE_REGISTRY[rule_id] = fn
        return fn
    return decorator

@register_rule("R-001")
def rule_taxonomy_compliance(chain: CandidateChain, query: NormalizedQuery) -> UnitCheckResult:
    """All process units must be in the controlled taxonomy."""
    taxonomy = get_taxonomy()
    invalid = taxonomy.validate_chain(chain.chain)
    if invalid:
        return UnitCheckResult(
            rule_id="R-001",
            rule_description="All process units must be in the controlled taxonomy",
            status=CheckStatus.FAIL,
            violated_by=str(invalid),
            message=f"Unknown units: {invalid}. Only taxonomy-approved units allowed.",
        )
    return UnitCheckResult(
        rule_id="R-001",
        rule_description="All process units must be in the controlled taxonomy",
        status=CheckStatus.PASS,
        message="All units are valid taxonomy entries.",
    )


@register_rule("R-002")
def rule_disinfection_barrier(chain: CandidateChain, query: NormalizedQuery) -> UnitCheckResult:
    """If the water is for drinking or microbial safety is required, a disinfection barrier is mandatory."""
    # Real taxonomy unit names (space-separated, case-insensitive check below)
    disinfection_units = {
        "chlorine", "chloramine", "chlorine dioxide",
        "ozone", "ozone and hydrogen peroxide",
        "ultraviolet irradiation",
        "ultraviolet irradiation and hydrogen peroxide",
        "ultraviolet irradiation and ozone",
    }
    c = query.constraints

    drinking_use = (c and c.use_for_drinking is True) or (
        query.context and "drink" in query.context.lower()
    )
    has_microbe = "e_coli" in (query.contaminants or [])

    if not (drinking_use or has_microbe):
        return UnitCheckResult(
            rule_id="R-002",
            rule_description="Disinfection barrier required for drinking / microbial safety",
            status=CheckStatus.NA,
            message="Disinfection requirement does not apply.",
        )

    chain_normalized = {u.strip().replace("_", " ").lower() for u in chain.chain}
    if chain_normalized & disinfection_units:
        return UnitCheckResult(
            rule_id="R-002",
            rule_description="Disinfection barrier required for drinking / microbial safety",
            status=CheckStatus.PASS,
            message="Disinfection barrier present.",
        )
    return UnitCheckResult(
        rule_id="R-002",
        rule_description="Disinfection barrier required for drinking / microbial safety",
        status=CheckStatus.FAIL,
        violated_by=chain.chain_id,
        message="No disinfection unit found; required for drinking/microbial safety.",
    )


@register_rule("R-003")
def rule_no_brine_disposal(chain: CandidateChain, query: NormalizedQuery) -> UnitCheckResult:
    """If brine_disposal is not available, reject chains containing membrane separation (RO/NF)."""
    # Real taxonomy names
    brine_units = {
        "membrane separation",
    }
    c = query.constraints
    if c is None or c.brine_disposal is not False:
        return UnitCheckResult(
            rule_id="R-003",
            rule_description="RO/NF prohibited when brine disposal is unavailable",
            status=CheckStatus.NA,
            message="Brine disposal constraint not set.",
        )

    chain_normalized = {u.strip().replace("_", " ").lower() for u in chain.chain}
    offenders = [u for u in chain.chain if u.strip().replace("_", " ").lower() in brine_units]
    if offenders:
        return UnitCheckResult(
            rule_id="R-003",
            rule_description="RO/NF prohibited when brine disposal is unavailable",
            status=CheckStatus.FAIL,
            violated_by=str(offenders),
            message=f"Chain contains {offenders} but brine disposal is not available.",
        )
    return UnitCheckResult(
        rule_id="R-003",
        rule_description="RO/NF prohibited when brine disposal is unavailable",
        status=CheckStatus.PASS,
        message="No brine-generating units; constraint satisfied.",
    )


@register_rule("R-004")
def rule_high_energy_penalty(chain: CandidateChain, query: NormalizedQuery) -> UnitCheckResult:
    """Penalize (WARN) high-energy chains when energy is limited."""
    c = query.constraints
    if c is None or c.energy != "limited":
        return UnitCheckResult(
            rule_id="R-004",
            rule_description="High-energy chains penalized when energy is limited",
            status=CheckStatus.NA,
            message="Energy constraint not restricted.",
        )

    # Real taxonomy names
    high_energy_units = {
        "membrane separation", "membrane filtration",
        "ozone", "ozone and hydrogen peroxide",
        "ultraviolet irradiation and ozone",
    }
    offenders = [
        u for u in chain.chain
        if u.strip().replace("_", " ").lower() in high_energy_units
    ]
    if offenders:
        return UnitCheckResult(
            rule_id="R-004",
            rule_description="High-energy chains penalized when energy is limited",
            status=CheckStatus.WARN,
            violated_by=str(offenders),
            message=f"High-energy units {offenders} present; penalizing score.",
        )
    return UnitCheckResult(
        rule_id="R-004",
        rule_description="High-energy chains penalized when energy is limited",
        status=CheckStatus.PASS,
        message="No high-energy units; constraint satisfied.",
    )



def get_all_rules() -> Dict[str, RuleFn]:
    """Return a copy of the rule registry."""
    return dict(_RULE_REGISTRY)


def apply_rules(
    chain: CandidateChain,
    query: NormalizedQuery,
    rule_ids: List[str] | None = None,
) -> List[UnitCheckResult]:
    """
    Apply rules to a single candidate chain.

    Parameters
    ----------
    chain:    The candidate chain to check.
    query:    The normalized user query (provides constraint context).
    rule_ids: Optional subset of rule IDs to run; runs all if None.
    """
    ids = rule_ids if rule_ids is not None else list(_RULE_REGISTRY.keys())
    results = []
    for rid in ids:
        fn = _RULE_REGISTRY.get(rid)
        if fn is None:
            continue
        results.append(fn(chain, query))
    return results
