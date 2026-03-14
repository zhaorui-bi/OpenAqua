"""Tests for TaxonomyManager.

Uses the real taxonomy.json (data/unit-level/taxonomy.json) and the real
TDB treatment-unit scan.  Unit names reflect the TDB file-naming convention:
Title-Case, space-separated (e.g. "Granular Activated Carbon", "Chlorine").
"""
import pytest
from app.core.taxonomy import TaxonomyManager


@pytest.fixture
def taxonomy():
    # Use default paths from settings (data/unit-level/taxonomy.json + tdb/)
    return TaxonomyManager()


def test_normalize_canonical_id(taxonomy):
    # Real canonical name is Title Case as stored in taxonomy.json
    assert taxonomy.normalize_contaminant("arsenic") == "Arsenic"
    assert taxonomy.normalize_contaminant("Arsenic") == "Arsenic"


def test_normalize_synonym(taxonomy):
    # "As" is a registered synonym for Arsenic in taxonomy.json
    assert taxonomy.normalize_contaminant("As") == "Arsenic"
    assert taxonomy.normalize_contaminant("Arsenate") == "Arsenic"


def test_normalize_unknown(taxonomy):
    assert taxonomy.normalize_contaminant("unobtanium") is None


def test_valid_unit(taxonomy):
    # Real unit names scanned from TDB treatment file names
    assert taxonomy.is_valid_unit("Granular Activated Carbon") is True
    assert taxonomy.is_valid_unit("Chlorine") is True
    assert taxonomy.is_valid_unit("magic_filter") is False
    assert taxonomy.is_valid_unit("coagulation") is False  # not a standalone TDB unit


def test_validate_chain_clean(taxonomy):
    # All three are real TDB treatment units
    errors = taxonomy.validate_chain(
        ["Granular Activated Carbon", "Ion Exchange", "Chlorine"]
    )
    assert errors == []


def test_validate_chain_with_bad_unit(taxonomy):
    errors = taxonomy.validate_chain(["Granular Activated Carbon", "unknown_process"])
    assert "unknown_process" in errors
    assert "Granular Activated Carbon" not in errors
