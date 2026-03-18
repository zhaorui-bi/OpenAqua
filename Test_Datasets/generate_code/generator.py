"""
generator.py
------------
Orchestrates a single case generation attempt:
  1. Build prompt (with optional retry feedback)
  2. Call LLM
  3. Extract JSON from response
  4. Validate schema
  5. Fix case_id and metadata fields if needed
  6. Return final dict or raise after max retries

Also provides helpers to write a case to disk and read the progress file.
"""

import asyncio
import json
import logging
import os
from typing import Dict, List, Optional

import config
import data_loader
import llm_client
import prompt_builder
import schema_validator
from contaminant_planner import CaseSpec

logger = logging.getLogger(__name__)



def _fixup(case: dict, spec: CaseSpec) -> dict:
    """
    Force-correct the case_id and metadata fields that must match
    the spec regardless of what the LLM produced.
    """
    case["case_id"]            = spec.case_id
    case["category_level_1"]   = spec.difficulty
    case.setdefault("metadata", {})
    case["metadata"]["difficulty"]        = spec.difficulty
    case["metadata"]["benchmark_split"]   = "test"
    case["metadata"]["language"]          = "en"
    case["metadata"]["case_source_type"]  = (
        "synthetic_case_based_on_public_water_treatment_knowledge"
    )
    return case



async def generate_case(
    spec:       CaseSpec,
    kb_cases:   List[dict],
    semaphore:  asyncio.Semaphore,
    max_retries: int = config.MAX_RETRIES,
) -> Optional[dict]:
    """
    Generate one benchmark case.

    Returns:
        dict  - validated case on success
        None  - if all retries are exhausted (caller logs failure)
    """
    feedback: Optional[str] = None

    for attempt in range(1, max_retries + 1):
        logger.info("[%s] Attempt %d/%d", spec.case_id, attempt, max_retries)

        # Build messages
        messages = prompt_builder.build_prompt(spec, kb_cases,
                                               retry_feedback=feedback)

        # Call LLM
        try:
            raw = await llm_client.call_llm(messages, semaphore)
        except llm_client.LLMError as exc:
            logger.error("[%s] LLM call failed: %s", spec.case_id, exc)
            feedback = f"API call failed on previous attempt: {exc}"
            continue

        # Extract JSON
        json_text = llm_client.extract_json(raw)
        if json_text is None:
            logger.warning("[%s] No JSON found in response.", spec.case_id)
            feedback = (
                "Previous response did not contain a parseable JSON object. "
                "Output ONLY a single JSON object."
            )
            continue

        # Validate
        errors = schema_validator.validate(json_text, expected_difficulty=spec.difficulty)
        if errors:
            feedback = schema_validator.errors_to_feedback(errors)
            logger.warning("[%s] Validation failed (%d errors): %s",
                           spec.case_id, len(errors), errors[:3])
            continue

        # Success – parse, fixup, return
        case = json.loads(json_text)
        case = _fixup(case, spec)
        logger.info("[%s] Generated successfully.", spec.case_id)
        return case

    logger.error("[%s] All %d attempts failed.", spec.case_id, max_retries)
    return None



def case_output_path(spec: CaseSpec) -> str:
    """Return the full file path where this case should be saved."""
    out_dir = config.OUTPUT_DIRS[spec.difficulty]
    return os.path.join(out_dir, f"{spec.case_id}.json")


def save_case(case: dict, spec: CaseSpec) -> None:
    """Write a case dict to its output JSON file."""
    path = case_output_path(spec)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(case, f, indent=2, ensure_ascii=False)



def load_progress() -> set:
    """Return the set of already-completed case_ids."""
    if not os.path.exists(config.PROGRESS_FILE):
        return set()
    try:
        with open(config.PROGRESS_FILE, encoding="utf-8") as f:
            data = json.load(f)
        return set(data.get("completed", []))
    except Exception:
        return set()


def save_progress(completed: set) -> None:
    """Persist the set of completed case_ids."""
    os.makedirs(os.path.dirname(config.PROGRESS_FILE), exist_ok=True)
    with open(config.PROGRESS_FILE, "w", encoding="utf-8") as f:
        json.dump({"completed": sorted(completed)}, f, indent=2)


def save_failed(failed: List[str]) -> None:
    """Persist the list of permanently-failed case_ids."""
    os.makedirs(os.path.dirname(config.FAILED_FILE), exist_ok=True)
    with open(config.FAILED_FILE, "w", encoding="utf-8") as f:
        json.dump({"failed": failed}, f, indent=2)
