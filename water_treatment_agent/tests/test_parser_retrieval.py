"""
Test: Task Parser Agent → Retrieval Agent pipeline.

Covers three input scenarios:
  1. Pure natural language (raw_query only)
  2. Structured JSON input (no raw_query)
  3. Mixed: raw_query + partial structured fields

Usage:
    cd water_treatment_agent
    python scripts/test_parser_retrieval.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.parser_agent import TaskParserAgent
from app.agents.retrieval_agent import RetrievalAgent
from app.core.schemas import UserConstraints, UserQuery, WaterQuality


GREEN = "\033[92m"
CYAN  = "\033[96m"
YELLOW= "\033[93m"
RESET = "\033[0m"

def header(title: str) -> None:
    print(f"\n{CYAN}{'='*60}{RESET}")
    print(f"{CYAN}  {title}{RESET}")
    print(f"{CYAN}{'='*60}{RESET}")

def ok(msg: str) -> None:
    print(f"{GREEN}✓ {msg}{RESET}")

def warn(msg: str) -> None:
    print(f"{YELLOW}⚠ {msg}{RESET}")



def make_nl_query() -> UserQuery:
    """Scenario 1: pure natural language input."""
    return UserQuery(
        query_id="TEST-NL-001",
        raw_query=(
            "我有一口农村地下水井，砷含量很高大约150微克/升，pH偏中性约7.2，"
            "预算有限，没有浓盐水处置设施，请推荐去除砷的处理工艺，"
            "需要达到WHO饮用水标准（砷<10 µg/L）"
        ),
    )


def make_structured_query() -> UserQuery:
    """Scenario 2: fully structured input (no NL)."""
    return UserQuery(
        query_id="TEST-ST-001",
        source_water="surface_water",
        water_quality=WaterQuality(
            pH=7.5,
            turbidity_NTU=50.0,
            e_coli_CFU_100mL=500.0,
        ),
        contaminants=["turbidity", "e_coli"],
        constraints=UserConstraints(
            budget="medium",
            use_for_drinking=True,
        ),
        context="municipal drinking water plant",
    )


def make_mixed_query() -> UserQuery:
    """Scenario 3: NL query + some explicit structured fields."""
    return UserQuery(
        query_id="TEST-MX-001",
        raw_query="地下水含有硝酸盐80mg/L，需要降低到50mg/L以下，欧盟标准",
        source_water="groundwater",       # explicit override
        constraints=UserConstraints(budget="medium"),
    )



def run_scenario(label: str, query: UserQuery) -> None:
    header(f"Scenario: {label}")

    parser = TaskParserAgent()
    retriever = RetrievalAgent()

    # ── Step 1: Parser ──
    print(f"\n[1/2] Running TaskParserAgent on query_id={query.query_id}")
    normalized = parser.run(query)

    ok(f"NormalizedQuery validated by Pydantic")
    print(f"  source_water  : {normalized.source_water}")
    print(f"  contaminants  : {normalized.contaminants}")
    print(f"  missing_fields: {normalized.missing_fields}")
    print(f"  assumptions   : {normalized.assumptions}")
    print(f"  notes         : {normalized.normalization_notes}")

    wq = normalized.water_quality.model_dump(exclude_none=True, exclude={"extra"})
    if wq:
        print(f"  water_quality : {wq}")

    c = normalized.constraints.model_dump(exclude_none=True, exclude={"extra"})
    if c:
        print(f"  constraints   : {c}")

    # ── Step 2: Retrieval ──
    print(f"\n[2/2] Running RetrievalAgent")
    bundle = retriever.run(normalized)

    ok(f"RetrievalBundle received — {bundle.total_retrieved} total chunks")
    print(f"  kb_unit     : {len(bundle.kb_unit)} chunks")
    print(f"  kb_template : {len(bundle.kb_template)} chunks")
    print(f"  kb_case     : {len(bundle.kb_case)} chunks")

    # Show top result per KB
    for kb_name, chunks in [
        ("kb_unit",     bundle.kb_unit),
        ("kb_template", bundle.kb_template),
        ("kb_case",     bundle.kb_case),
    ]:
        if chunks:
            top = chunks[0]
            print(f"\n  {YELLOW}Top {kb_name}{RESET}")
            print(f"    chunk_id      : {top.chunk_id}")
            print(f"    relevance     : {top.relevance_score:.4f}  "
                  f"(bm25={top.bm25_score:.3f}, overlap={top.embedding_score:.3f})")
            print(f"    coverage_tags : {top.coverage_tags}")
            print(f"    text preview  : {top.text[:120].strip()}…")
        else:
            warn(f"No chunks returned for {kb_name}")

    # ── Schema contract check ──
    print(f"\n  Pydantic round-trip check …")
    bundle.model_validate(bundle.model_dump())
    ok("RetrievalBundle schema valid")


def main() -> None:
    print(f"\n{CYAN}Water Treatment Agent — Parser + Retrieval Pipeline Test{RESET}")

    run_scenario("Natural Language Input", make_nl_query())
    run_scenario("Structured Input",       make_structured_query())
    run_scenario("Mixed Input",            make_mixed_query())

    print(f"\n{GREEN}All scenarios completed successfully.{RESET}\n")


if __name__ == "__main__":
    main()
