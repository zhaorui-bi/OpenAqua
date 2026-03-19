"""
main.py
-------
Entry point for the WContBench dataset generation pipeline.

Usage:
    python main.py                    # generate all 337 cases
    python main.py --difficulty easy  # only easy cases
    python main.py --retry-failed     # re-run previously failed cases
    python main.py --dry-run          # print plan without calling API
    python main.py --coverage-report  # print contaminant coverage and exit

The script is resumable: already-completed case_ids are skipped.
"""

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from typing import Dict, List, Optional

import config
import contaminant_planner
import data_loader
import generator
from contaminant_planner import CaseSpec

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s – %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),                         
        logging.FileHandler("generation.log", encoding="utf-8"),  
    ]
)
logger = logging.getLogger("main")


async def run_batch(
    specs:     List[CaseSpec],
    kb_cases:  List[dict],
    completed: set,
    failed:    List[str],
) -> None:
    """
    Run generation for all specs in `specs`, skipping already-completed ones.
    Updates `completed` and `failed` in-place and persists progress after
    each case.
    """
    semaphore = asyncio.Semaphore(config.CONCURRENCY)

    tasks = {}
    for spec in specs:
        if spec.case_id in completed:
            logger.info("[%s] Already done - skipping.", spec.case_id)
            continue
        task = asyncio.create_task(
            generator.generate_case(spec, kb_cases, semaphore),
            name=spec.case_id,
        )
        tasks[spec.case_id] = (task, spec)

        total   = len(tasks)
        done_n  = 0
        start   = time.time()

        for case_id, (task, spec) in tasks.items():
            case = await task
            done_n += 1
            elapsed = time.time() - start

            if case is not None:
                generator.save_case(case, spec)
                completed.add(case_id)
                generator.save_progress(completed)
                logger.info(
                    "✓ [%d/%d] %s saved  (%.0fs elapsed)",
                    done_n, total, case_id, elapsed,
                )
            else:
                failed.append(case_id)
                generator.save_failed(failed)
                logger.error(
                    "✗ [%d/%d] %s FAILED permanently",
                    done_n, total, case_id,
                )


def print_coverage_report(specs: Dict[str, List[CaseSpec]]) -> None:
    print("\n" + "=" * 60)
    print(contaminant_planner.coverage_report(specs))
    print("=" * 60 + "\n")


def dry_run(specs: Dict[str, List[CaseSpec]]) -> None:
    print_coverage_report(specs)
    print("Dry-run plan (first 5 per difficulty):")
    for diff, cases in specs.items():
        print(f"\n  [{diff.upper()}]")
        for s in cases[:5]:
            print(f"    {s.case_id}  contaminants={s.contaminants}  "
                  f"source={s.water_source}  use={s.effluent_use}")
            if s.use_alias_for:
                print(f"             alias: '{s.use_alias_for}'")
    print("\nNo API calls made (dry-run mode).")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate WContBench water-treatment benchmark cases via LLM."
    )
    parser.add_argument(
        "--difficulty", choices=["easy", "middle", "difficult"],
        help="Generate only one difficulty level.",
    )
    parser.add_argument(
        "--retry-failed", action="store_true",
        help="Re-attempt cases listed in failed_cases.json.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print the generation plan without calling the API.",
    )
    parser.add_argument(
        "--coverage-report", action="store_true",
        help="Print contaminant coverage statistics and exit.",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed for contaminant planner (default: 42).",
    )
    parser.add_argument(
        "--concurrency", type=int, default=config.CONCURRENCY,
        help=f"Max simultaneous API requests (default: {config.CONCURRENCY}).",
    )
    return parser.parse_args()


async def main_async(args: argparse.Namespace) -> None:
    logger.info("Building contaminant coverage plan (seed=%d)…", args.seed)
    all_specs = contaminant_planner.build_case_specs(seed=args.seed)

    if args.coverage_report:
        print_coverage_report(all_specs)
        return

    if args.dry_run:
        dry_run(all_specs)
        return

    if config.OPENROUTER_API_KEY == "YOUR_API_KEY_HERE":
        logger.error("Please set OPENROUTER_API_KEY in config.py before running.")
        sys.exit(1)

    logger.info("Loading KB cases…")
    kb_cases = data_loader.load_kb_cases()
    logger.info("  %d KB cases loaded.", len(kb_cases))

    logger.info("Loading taxonomy…")
    unique_names, synonym_map = data_loader.load_taxonomy()
    logger.info("  %d unique contaminants in taxonomy.", len(unique_names))

    completed = generator.load_progress()
    failed: List[str] = []

    if args.retry_failed:
        if not os.path.exists(config.FAILED_FILE):
            logger.warning("No failed_cases.json found – nothing to retry.")
            return
        with open(config.FAILED_FILE, encoding="utf-8") as f:
            failed_ids = set(json.load(f).get("failed", []))
        specs_to_run: List[CaseSpec] = [
            s
            for cases in all_specs.values()
            for s in cases
            if s.case_id in failed_ids
        ]
        # Reset their "failed" status so they can be retried fresh
        failed = [fid for fid in failed_ids if fid not in {s.case_id for s in specs_to_run}]
        logger.info("Retrying %d previously failed cases.", len(specs_to_run))

    elif args.difficulty:
        specs_to_run = all_specs[args.difficulty]
        logger.info(
            "Generating %d cases for difficulty '%s'.",
            len(specs_to_run), args.difficulty,
        )

    else:
        specs_to_run = [s for cases in all_specs.values() for s in cases]
        logger.info("Generating all %d new cases.", len(specs_to_run))

    pending = [s for s in specs_to_run if s.case_id not in completed]
    logger.info(
        "Plan: %d total | %d already done | %d to generate",
        len(specs_to_run), len(specs_to_run) - len(pending), len(pending),
    )
    if not pending:
        logger.info("All cases already completed.")
        return

    config.CONCURRENCY = args.concurrency   # allow CLI override
    t0 = time.time()
    await run_batch(pending, kb_cases, completed, failed)
    elapsed = time.time() - t0

    n_ok   = len([s for s in specs_to_run if s.case_id in completed])
    n_fail = len(failed)
    logger.info(
        "\n══ Generation complete ══\n"
        "  Elapsed   : %.0f s\n"
        "  Succeeded : %d\n"
        "  Failed    : %d\n"
        "  Output dir: %s",
        elapsed, n_ok, n_fail, config.TEST_DATA_DIR,
    )
    if failed:
        logger.warning("Failed case IDs saved to: %s", config.FAILED_FILE)
        logger.warning("Re-run with --retry-failed to attempt them again.")


def main() -> None:
    args = parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
