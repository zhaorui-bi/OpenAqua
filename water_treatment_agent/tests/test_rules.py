"""Tests for the constraint rule library."""
import pytest
from app.core.rules import apply_rules
from app.core.schemas import (
    CandidateChain,
    CheckStatus,
    NormalizedQuery,
    UserConstraints,
    WaterQuality,
    TreatmentTargets,
)


def _make_query(**kwargs):
    defaults = dict(
        query_id="test-001",
        source_water="groundwater",
        water_quality=WaterQuality(),
        contaminants=["arsenic"],
        treatment_targets=TreatmentTargets(),
        constraints=UserConstraints(),
    )
    defaults.update(kwargs)
    return NormalizedQuery(**defaults)


def _make_chain(chain, chain_id="C-001", generates_brine=False):
    return CandidateChain(
        chain_id=chain_id,
        chain=chain,
        key_units=chain[:1],
        rationale="test",
        generates_brine=generates_brine,
    )


def test_taxonomy_compliance_pass():
    # Use real TDB taxonomy unit names (Title Case, space-separated)
    chain = _make_chain(["Granular Activated Carbon", "Ion Exchange", "Chlorine"])
    query = _make_query()
    results = apply_rules(chain, query, rule_ids=["R-001"])
    assert results[0].status == CheckStatus.PASS


def test_taxonomy_compliance_fail():
    chain = _make_chain(["coagulation", "magic_process"])
    query = _make_query()
    results = apply_rules(chain, query, rule_ids=["R-001"])
    assert results[0].status == CheckStatus.FAIL


def test_no_brine_rule_fail():
    chain = _make_chain(["filtration", "Membrane Separation"], generates_brine=True)
    query = _make_query(constraints=UserConstraints(brine_disposal=False))
    results = apply_rules(chain, query, rule_ids=["R-003"])
    assert results[0].status == CheckStatus.FAIL


def test_no_brine_rule_pass():
    chain = _make_chain(["coagulation", "filtration", "Chlorine"])
    query = _make_query(constraints=UserConstraints(brine_disposal=False))
    results = apply_rules(chain, query, rule_ids=["R-003"])
    assert results[0].status == CheckStatus.PASS


def test_disinfection_required():
    chain = _make_chain(["coagulation", "filtration"])  # no disinfection
    query = _make_query(
        contaminants=["e_coli"],
        constraints=UserConstraints(use_for_drinking=True),
    )
    results = apply_rules(chain, query, rule_ids=["R-002"])
    assert results[0].status == CheckStatus.FAIL


def test_disinfection_present():
    chain = _make_chain(["coagulation", "filtration", "Chlorine"])
    query = _make_query(
        contaminants=["e_coli"],
        constraints=UserConstraints(use_for_drinking=True),
    )
    results = apply_rules(chain, query, rule_ids=["R-002"])
    assert results[0].status == CheckStatus.PASS
