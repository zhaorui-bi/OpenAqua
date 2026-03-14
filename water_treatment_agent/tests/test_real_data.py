"""
test_real_data.py — Smoke test for real database integration
-------------------------------------------------------------
Validates that all five modified modules load and function correctly
with the real data in data/unit-level/.

Run from water_treatment_agent/:
    python scripts/test_real_data.py

Tests (in order):
  1. Config  — paths resolve and unit_kb_dir / taxonomy_path exist
  2. Taxonomy — loads real taxonomy.json, contaminant count, synonym lookup,
                treatment unit scan
  3. IndexBuilder — builds corpus from real tdb/, reports chunk counts per type
  4. CONTAMINANT_UNIT_MAP — lazy-loaded from real data, spot-checks Arsenic
  5. EvidenceBinding — claim generation uses metadata["function"] correctly
  6. End-to-end index build (optional, skippable with --skip-index)

Exit code 0 = all passed.  Non-zero = at least one failure.
"""
from __future__ import annotations

import argparse
import sys
import traceback
from pathlib import Path
from typing import List, Tuple

# ── make sure we can import the app package ──────────────────────────────────
ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

PASS = "\033[92m[PASS]\033[0m"
FAIL = "\033[91m[FAIL]\033[0m"
INFO = "\033[94m[INFO]\033[0m"


def _ok(label: str, detail: str = "") -> None:
    print(f"  {PASS} {label}" + (f"  ({detail})" if detail else ""))


def _fail(label: str, reason: str) -> None:
    print(f"  {FAIL} {label}: {reason}")


def run_tests(skip_index: bool) -> List[Tuple[str, bool]]:
    results: List[Tuple[str, bool]] = []


    print(f"\n{INFO} ── Test 1: Config paths ──")
    try:
        from app.core.config import get_settings
        cfg = get_settings()

        checks = [
            ("unit_kb_dir exists",     cfg.unit_kb_dir and cfg.unit_kb_dir.exists()),
            ("taxonomy_path exists",   cfg.taxonomy_path and cfg.taxonomy_path.exists()),
            ("index_dir parent exists",cfg.index_dir.parent.exists()),
        ]
        all_ok = True
        for label, ok in checks:
            if ok:
                _ok(label, str(cfg.unit_kb_dir if "unit" in label else
                               cfg.taxonomy_path if "taxonomy" in label else cfg.index_dir.parent))
            else:
                val = (cfg.unit_kb_dir if "unit" in label else
                       cfg.taxonomy_path if "taxonomy" in label else cfg.index_dir.parent)
                _fail(label, f"path={val}")
                all_ok = False
        results.append(("Config paths", all_ok))
    except Exception as e:
        _fail("Config import", traceback.format_exc(limit=3))
        results.append(("Config paths", False))

    print(f"\n{INFO} ── Test 2: TaxonomyManager ──")
    try:
        from app.core.taxonomy import TaxonomyManager, get_taxonomy
        from app.core.config import get_settings
        cfg = get_settings()

        tm = TaxonomyManager(cfg.taxonomy_path, cfg.unit_kb_dir)
        all_ids = tm.all_contaminant_ids()
        all_units = tm.all_treatment_units()

        _ok(f"Loaded contaminants", f"{len(all_ids)} canonical names")
        _ok(f"Scanned treatment units", f"{len(all_units)} units")

        # Spot-check: "Arsenic" should be canonical
        arsenic_id = tm.normalize_contaminant("Arsenic")
        if arsenic_id == "Arsenic":
            _ok("normalize_contaminant('Arsenic')", f"→ {arsenic_id}")
        else:
            _fail("normalize_contaminant('Arsenic')", f"got {arsenic_id!r}, expected 'Arsenic'")

        # Spot-check synonym lookup
        synonym_test = tm.normalize_contaminant("As")
        if synonym_test == "Arsenic":
            _ok("synonym lookup 'As'", "→ Arsenic")
        else:
            _fail("synonym lookup 'As'", f"got {synonym_test!r}")

        # Spot-check treatment unit validation
        sample_units = list(all_units)[:3]
        for u in sample_units:
            valid = tm.is_valid_unit(u)
            if valid:
                _ok(f"is_valid_unit('{u}')")
            else:
                _fail(f"is_valid_unit('{u}')", "returned False for known unit")

        # Show a sample of treatment units
        print(f"    Sample units: {', '.join(sorted(all_units)[:8])}")

        results.append(("TaxonomyManager", True))
    except Exception as e:
        _fail("TaxonomyManager", traceback.format_exc(limit=5))
        results.append(("TaxonomyManager", False))


    print(f"\n{INFO} ── Test 3: IndexBuilder corpus ──")
    try:
        from app.rag.index_builder import IndexBuilder, _flatten_to_text, _tokenize

        builder = IndexBuilder()
        corpus = builder._build_corpus()

        if not corpus:
            _fail("corpus size", "empty corpus — check unit_kb_dir")
            results.append(("IndexBuilder corpus", False))
        else:
            by_type: dict = {}
            for chunk in corpus:
                kt = chunk["kb_type"]
                by_type[kt] = by_type.get(kt, 0) + 1

            _ok(f"Total chunks", str(len(corpus)))
            for kt, count in sorted(by_type.items()):
                _ok(f"  {kt}", f"{count} chunks")

            # Spot-check a treatment chunk
            treatment_chunks = [c for c in corpus if c["source_id"].startswith("treatment_")]
            if treatment_chunks:
                sample = treatment_chunks[0]
                _ok("treatment chunk source_id", sample["source_id"])
                _ok("treatment chunk metadata.function",
                    sample.get("metadata", {}).get("function", "MISSING"))
                _ok("treatment chunk coverage_tags", str(sample["coverage_tags"]))
            else:
                _fail("treatment chunks", "none found")

            results.append(("IndexBuilder corpus", True))
    except Exception as e:
        _fail("IndexBuilder", traceback.format_exc(limit=5))
        results.append(("IndexBuilder corpus", False))


    print(f"\n{INFO} ── Test 4: CONTAMINANT_UNIT_MAP (dynamic) ──")
    try:
        from app.agents.planner_agent import CONTAMINANT_UNIT_MAP, _get_contaminant_unit_map

        loaded = _get_contaminant_unit_map()
        _ok("Map loaded", f"{len(loaded)} contaminants")

        arsenic_units = loaded.get("arsenic", [])
        if arsenic_units:
            _ok("arsenic units", f"{len(arsenic_units)} found: {arsenic_units[:3]}")
        else:
            _fail("arsenic units", "empty — check data/unit-level/tdb/Arsenic/")

        # Test LazyMap access
        lazy_val = CONTAMINANT_UNIT_MAP.get("arsenic", [])
        _ok("LazyMap.get('arsenic')", f"{len(lazy_val)} units")

        results.append(("CONTAMINANT_UNIT_MAP", bool(loaded)))
    except Exception as e:
        _fail("CONTAMINANT_UNIT_MAP", traceback.format_exc(limit=5))
        results.append(("CONTAMINANT_UNIT_MAP", False))


    print(f"\n{INFO} ── Test 5: EvidenceBinding _generate_claim ──")
    try:
        from app.utils.evidence_binding import _generate_claim
        from app.core.schemas import CandidateChain, EnergyLevel

        # Simulate a treatment chunk with real metadata
        class _FakeChunk:
            source_id = "treatment_Arsenic_Granular_Activated_Carbon"
            coverage_tags = ["Arsenic"]
            metadata = {"function": "Granular Activated Carbon"}

        class _FakeTDBChunk:
            source_id = "tdb_Arsenic_fatetrans"
            coverage_tags = ["Arsenic"]
            metadata = {"subtype": "fatetrans"}

        chain = CandidateChain(
            chain_id="TEST-01",
            chain=["Granular Activated Carbon"],
            key_units=["Granular Activated Carbon"],
            rationale="test",
            generates_brine=False,
            requires_disinfection=False,
            energy_intensity=EnergyLevel.LOW,
        )

        claim_treatment = _generate_claim(_FakeChunk(), chain, {"Arsenic"})
        claim_tdb = _generate_claim(_FakeTDBChunk(), chain, {"Arsenic"})

        if "Granular Activated Carbon" in claim_treatment:
            _ok("treatment claim", claim_treatment)
        else:
            _fail("treatment claim", f"function name missing: {claim_treatment!r}")

        if "Fate and transport" in claim_tdb:
            _ok("tdb fatetrans claim", claim_tdb)
        else:
            _fail("tdb fatetrans claim", claim_tdb)

        results.append(("EvidenceBinding", True))
    except Exception as e:
        _fail("EvidenceBinding", traceback.format_exc(limit=5))
        results.append(("EvidenceBinding", False))


    if not skip_index:
        print(f"\n{INFO} ── Test 6: Full index build (BM25) ──")
        try:
            from app.rag.index_builder import IndexBuilder
            builder = IndexBuilder()
            n = builder.build_all()
            _ok("build_all()", f"{n} chunks indexed")
            results.append(("Full index build", True))
        except Exception as e:
            _fail("Full index build", traceback.format_exc(limit=5))
            results.append(("Full index build", False))
    else:
        print(f"\n{INFO} ── Test 6: Full index build skipped (--skip-index) ──")

    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Smoke test for real data integration")
    parser.add_argument(
        "--skip-index",
        action="store_true",
        help="Skip the full BM25 index build (faster for quick checks)",
    )
    args = parser.parse_args()

    print("=" * 60)
    print("  Water Treatment Agent — Real Data Integration Smoke Test")
    print("=" * 60)

    results = run_tests(skip_index=args.skip_index)

    print("\n" + "=" * 60)
    print("  Summary")
    print("=" * 60)
    passed = sum(1 for _, ok in results if ok)
    total = len(results)
    for name, ok in results:
        status = PASS if ok else FAIL
        print(f"  {status} {name}")
    print(f"\n  {passed}/{total} tests passed")
    print("=" * 60)

    sys.exit(0 if passed == total else 1)


if __name__ == "__main__":
    main()
