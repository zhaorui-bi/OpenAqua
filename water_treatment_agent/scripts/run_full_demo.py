"""
run_full_demo.py — Step-by-step 5-agent pipeline demo
------------------------------------------------------
Runs each agent individually, saves an intermediate JSON at every step,
and writes all log messages to a timestamped log file.

Usage (from water_treatment_agent/):
    python scripts/run_full_demo.py

Outputs  →  data/processed/runs/<YYYYMMDD_HHMMSS>/
    01_normalized_query.json    ← TaskParserAgent
    02_retrieval_bundle.json    ← RetrievalAgent
    03_candidates.json          ← ProcessPlannerAgent
    04_constraint_report.json   ← ConstraintCriticAgent
    05_final_report.json        ← ExplanationAgent
    05_final_report.md          ← Human-readable Markdown summary
    pipeline.log                ← Full log (all INFO messages)

Requires OPENROUTER_API_KEY in .env for LLM agents.
Falls back to rule/template mode automatically if the key is absent.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

RUN_TS = datetime.now().strftime("%Y%m%d_%H%M%S")
OUT_DIR = ROOT / "data" / "processed" / "runs" / RUN_TS
OUT_DIR.mkdir(parents=True, exist_ok=True)
LOG_PATH = OUT_DIR / "pipeline.log"

from app.core.logger import get_logger, setup_file_logging  # noqa: E402

setup_file_logging(LOG_PATH, level="INFO")
log = get_logger("run_full_demo")



def _banner(step: int, title: str) -> None:
    print(f"\n{'='*64}")
    print(f"  STEP {step}/5 — {title}")
    print(f"{'='*64}")
    log.info("=" * 60)
    log.info("STEP %d/5 — %s", step, title)
    log.info("=" * 60)


def _save_json(data: Dict[str, Any], filename: str) -> Path:
    path = OUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    log.info("Saved → %s", path.relative_to(ROOT))
    return path


def _save_markdown(content: str, filename: str) -> Path:
    path = OUT_DIR / filename
    with open(path, "w", encoding="utf-8") as f:
        f.write(content)
    log.info("Saved → %s", path.relative_to(ROOT))
    return path


def _build_markdown_report(report: Any) -> str:
    """Convert FinalReport to a readable Markdown document."""
    lines = []
    lines.append("# Water Treatment Recommendation Report")
    lines.append(f"\n**Query ID:** `{report.query_id}`  ")
    lines.append(f"**Pipeline Version:** `{report.pipeline_version}`  ")
    lines.append(f"**Generated:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")

    nq = report.normalized_query
    lines.append("---\n## 1. Normalized Query\n")
    lines.append(f"- **Source water:** {nq.source_water}")
    lines.append(f"- **Contaminants:** {', '.join(nq.contaminants) or '(none detected)'}")
    if nq.missing_fields:
        lines.append(f"- **Missing fields:** {', '.join(nq.missing_fields)}")
    if nq.assumptions:
        lines.append("\n**Assumptions made by parser:**")
        for a in nq.assumptions:
            lines.append(f"  - {a}")
    if nq.normalization_notes:
        lines.append("\n**Normalization notes:**")
        for n in nq.normalization_notes:
            lines.append(f"  - {n}")

    c = nq.constraints
    lines.append("\n**Constraints:**")
    lines.append(f"  - Drinking water use: `{c.use_for_drinking}`")
    lines.append(f"  - Brine disposal available: `{c.brine_disposal}`")
    lines.append(f"  - Budget: `{c.budget}`")
    lines.append(f"  - Energy: `{c.energy}`")

    if report.system_notes:
        lines.append("\n**System notes:**")
        for note in report.system_notes:
            lines.append(f"  > {note}")

    lines.append("\n---\n## 2. Ranked Recommendations\n")
    for rec in report.recommendations:
        lines.append(f"### Rank #{rec.rank} — `{rec.chain_id}`\n")
        lines.append(f"**Process chain:**  \n`{' → '.join(rec.chain)}`\n")

        # Score breakdown
        s = rec.rank_score
        lines.append("**Score breakdown:**\n")
        lines.append("| Component | Score |")
        lines.append("|-----------|-------|")
        lines.append(f"| **Total** | **{s.total:.3f}** |")
        lines.append(f"| Coverage  | {s.coverage_score:.3f} |")
        lines.append(f"| Constraint | {s.constraint_score:.3f} |")
        lines.append(f"| Evidence  | {s.evidence_score:.3f} |")
        lines.append(f"| Risk penalty | {s.risk_penalty:.3f} |")

        lines.append(f"\n**Uncertainty level:** `{rec.uncertainty.value}`  ")
        lines.append(f"**Constraint status:** `{rec.constraint_report.overall_status.value}`\n")

        # Constraint checks detail
        if rec.constraint_report.checks:
            lines.append("**Constraint checks:**\n")
            for chk in rec.constraint_report.checks:
                icon = "✓" if chk.status.value == "PASS" else ("⚠" if chk.status.value == "WARNING" else "✗")
                lines.append(f"  - [{chk.rule_id}] {icon} `{chk.status.value}` — {chk.message}")
        if rec.constraint_report.revision_actions:
            lines.append("\n**Revision actions applied:**")
            for act in rec.constraint_report.revision_actions:
                lines.append(f"  - {act}")

        # Why it works
        lines.append(f"\n**Why it works:**\n\n{rec.why_it_works}\n")

        # Risks
        if rec.risks:
            lines.append("**Risks:**")
            for r in rec.risks:
                lines.append(f"  - {r}")

        # Evidence citations
        if rec.evidence:
            lines.append(f"\n**Evidence citations** ({len(rec.evidence)}):\n")
            for e in rec.evidence:
                lines.append(f"  - **[{e.source_id}]** `{e.support_type}`")
                lines.append(f"    - *Claim:* {e.claim}")
                lines.append(f"    - *Excerpt:* \"{e.text_excerpt[:200]}\"")
        else:
            lines.append("\n> **Evidence:** No evidence citations retrieved — "
                         "verify against primary literature.")

        # Assumptions
        if rec.assumptions:
            lines.append("\n**Assumptions:**")
            for a in rec.assumptions:
                lines.append(f"  - {a}")

        lines.append("")  # blank line between recommendations

    lines.append("---\n*Report generated automatically by WaterTreatmentAgent pipeline.*\n")
    return "\n".join(lines)



def main() -> None:
    log.info("run_full_demo started — output dir: %s", OUT_DIR)
    print(f"\n{'='*64}")
    print("  Water Treatment Agent — Full Pipeline Demo")
    print(f"  Output directory: {OUT_DIR.relative_to(ROOT)}")
    print(f"  Log file        : {LOG_PATH.relative_to(ROOT)}")
    print(f"{'='*64}")

    # ── Imports (after path and logging setup) ─────────────────────────────
    from app.agents.critic_agent import ConstraintCriticAgent
    from app.agents.explanation_agent import ExplanationAgent
    from app.agents.parser_agent import TaskParserAgent
    from app.agents.planner_agent import ProcessPlannerAgent
    from app.agents.retrieval_agent import RetrievalAgent
    from app.core.config import get_settings
    from app.core.schemas import UserConstraints, UserQuery, WaterQuality

    settings = get_settings()
    llm_mode = bool(settings.openrouter_api_key)
    print(f"\n  LLM mode: {'ON  (OPENROUTER_API_KEY found)' if llm_mode else 'OFF (rule/template fallback)'}")

    # ── Build demo query ───────────────────────────────────────────────────
    query = UserQuery(
        raw_query=(
            "我有一口地下水井，砷浓度约 25 ug/L，超过 WHO 的 10 ug/L 饮用水标准。"
            "pH 约 7.2，铁含量较低（< 0.1 mg/L）。"
            "希望处理后用于饮用，预算中等，没有浓盐水处置设施。"
        ),
        source_water="groundwater",
        water_quality=WaterQuality(pH=7.2, iron_mg_L=0.08),
        contaminants=["Arsenic"],
        constraints=UserConstraints(
            use_for_drinking=True,
            brine_disposal=False,
            budget="medium",
        ),
        context="drinking water treatment for rural well — arsenic removal",
    )

    log.info("Demo query built: contaminants=%s source_water=%s",
             query.contaminants, query.source_water)
    print("\n[INPUT QUERY]")
    print(f"  Raw query    : {(query.raw_query or '')[:80]}...")
    print(f"  Contaminants : {query.contaminants}")
    print(f"  Source water : {query.source_water}")
    print(f"  Constraints  : drinking={query.constraints.use_for_drinking}, "
          f"brine={query.constraints.brine_disposal}, budget={query.constraints.budget}")

    t_total = time.time()

    _banner(1, "Task Parser Agent")
    t0 = time.time()
    parser = TaskParserAgent()
    normalized = parser.run(query)
    elapsed = time.time() - t0

    print(f"\n  query_id     : {normalized.query_id}")
    print(f"  contaminants : {normalized.contaminants}")
    print(f"  missing      : {normalized.missing_fields}")
    print(f"  assumptions  : {len(normalized.assumptions)} item(s)")
    print(f"  notes        : {len(normalized.normalization_notes)} item(s)")
    print(f"  elapsed      : {elapsed:.2f}s")
    log.info("Step 1 done in %.2fs — contaminants=%s missing=%s",
             elapsed, normalized.contaminants, normalized.missing_fields)

    _save_json(normalized.model_dump(mode="json"), "01_normalized_query.json")

    _banner(2, "Retrieval Agent")
    t0 = time.time()
    retriever = RetrievalAgent()
    retrieval = retriever.run(normalized)
    elapsed = time.time() - t0

    print(f"\n  total chunks   : {retrieval.total_retrieved}")
    print(f"  kb_unit chunks : {len(retrieval.kb_unit)}")
    print(f"  kb_case        : {len(retrieval.kb_case)}")
    if retrieval.kb_unit:
        top = retrieval.kb_unit[0]
        print(f"  top kb_unit    : [{top.source_id}] score={top.relevance_score:.3f}")
        print(f"    text excerpt : {top.text[:120]}...")
    print(f"  elapsed        : {elapsed:.2f}s")
    log.info("Step 2 done in %.2fs — total_retrieved=%d", elapsed, retrieval.total_retrieved)

    _save_json(retrieval.model_dump(mode="json"), "02_retrieval_bundle.json")

    _banner(3, "Process Planning Agent")
    t0 = time.time()
    planner = ProcessPlannerAgent()
    candidates = planner.run(normalized, retrieval)
    elapsed = time.time() - t0

    print(f"\n  candidates generated : {len(candidates.candidates)}")
    for i, c in enumerate(candidates.candidates, 1):
        print(f"  [{i}] {c.chain_id}")
        print(f"       chain         : {' → '.join(c.chain)}")
        print(f"       energy        : {c.energy_intensity}")
        print(f"       generates_brine: {c.generates_brine}")
        print(f"       rationale     : {c.rationale[:100]}...")
    if candidates.planning_notes:
        print(f"  planning_notes : {candidates.planning_notes}")
    print(f"  elapsed        : {elapsed:.2f}s")
    log.info("Step 3 done in %.2fs — %d candidates", elapsed, len(candidates.candidates))

    _save_json(candidates.model_dump(mode="json"), "03_candidates.json")

    _banner(4, "Constraint / Critic Agent")
    t0 = time.time()
    critic = ConstraintCriticAgent()
    constraint_report = critic.run(candidates, normalized)
    elapsed = time.time() - t0

    print(f"\n  chains evaluated : {len(constraint_report.chain_reports)}")
    print(f"  chains to revise : {constraint_report.chains_to_revise}")
    print(f"  chains to drop   : {constraint_report.chains_to_drop}")
    for cr in constraint_report.chain_reports:
        print(f"\n  [{cr.chain_id}]  overall={cr.overall_status.value}")
        for chk in cr.checks:
            print(f"    {chk.rule_id}: {chk.status.value:8s}  {chk.message}")
        if cr.revision_actions:
            print(f"    revision_actions: {cr.revision_actions}")
    print(f"\n  elapsed : {elapsed:.2f}s")
    log.info("Step 4 done in %.2fs — revise=%s drop=%s",
             elapsed, constraint_report.chains_to_revise, constraint_report.chains_to_drop)

    _save_json(constraint_report.model_dump(mode="json"), "04_constraint_report.json")

    # Also extract revision_actions as separate file for quick reference
    revision_summary = {
        "query_id": constraint_report.query_id,
        "chains_to_revise": constraint_report.chains_to_revise,
        "chains_to_drop": constraint_report.chains_to_drop,
        "revision_actions": {
            cr.chain_id: cr.revision_actions
            for cr in constraint_report.chain_reports
            if cr.revision_actions
        },
    }
    _save_json(revision_summary, "04_revision_actions.json")

    _banner(5, "Explanation Agent")
    t0 = time.time()
    explainer = ExplanationAgent()
    report = explainer.run(normalized, candidates, retrieval, constraint_report, top_k=3)
    elapsed = time.time() - t0

    print(f"\n  recommendations : {len(report.recommendations)}")
    if report.system_notes:
        for note in report.system_notes:
            print(f"  [NOTE] {note}")
    for rec in report.recommendations:
        print(f"\n  Rank #{rec.rank}  {rec.chain_id}")
        print(f"    chain       : {' → '.join(rec.chain)}")
        print(f"    score       : total={rec.rank_score.total:.3f}  "
              f"cov={rec.rank_score.coverage_score:.3f}  "
              f"ev={rec.rank_score.evidence_score:.3f}  "
              f"con={rec.rank_score.constraint_score:.3f}")
        print(f"    uncertainty : {rec.uncertainty.value}")
        print(f"    evidence    : {len(rec.evidence)} citation(s)")
        print(f"    why         : {(rec.why_it_works or '')[:150]}...")
    print(f"\n  elapsed : {elapsed:.2f}s")
    log.info("Step 5 done in %.2fs — %d recommendations", elapsed, len(report.recommendations))

    # Save JSON
    _save_json(report.model_dump(mode="json"), "05_final_report.json")

    # Save Markdown
    md_content = _build_markdown_report(report)
    _save_markdown(md_content, "05_final_report.md")

    # ── Final summary ──────────────────────────────────────────────────────
    total_elapsed = time.time() - t_total
    print(f"\n{'='*64}")
    print("  Pipeline complete!")
    print(f"  Total elapsed : {total_elapsed:.2f}s")
    print(f"\n  Output files in: {OUT_DIR.relative_to(ROOT)}")
    print("    01_normalized_query.json   ← TaskParserAgent output")
    print("    02_retrieval_bundle.json   ← RetrievalAgent output")
    print("    03_candidates.json         ← ProcessPlannerAgent output")
    print("    04_constraint_report.json  ← ConstraintCriticAgent output")
    print("    04_revision_actions.json   ← Revision action summary")
    print("    05_final_report.json       ← Final report (full)")
    print("    05_final_report.md         ← Human-readable Markdown report")
    print(f"    pipeline.log               ← Full log file")
    print(f"{'='*64}\n")
    log.info("run_full_demo finished — total %.2fs", total_elapsed)


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        import traceback
        log.exception("run_full_demo failed: %s", exc)
        traceback.print_exc()
        sys.exit(1)
