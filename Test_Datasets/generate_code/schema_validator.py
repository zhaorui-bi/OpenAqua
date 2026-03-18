"""
schema_validator.py
-------------------
Validates that a generated JSON string conforms to the WContBench case schema.

Returns a list of error strings; empty list means valid.
"""

import json
from typing import Any, Dict, List, Optional



_TOP_LEVEL_REQUIRED: Dict[str, type] = {
    "case_id":             str,
    "case_name":           str,
    "category_level_1":    str,
    "category_level_2":    dict,
    "task_description":    str,
    "input_data":          dict,
    "expected_output_format": dict,
    "reference_answer":    dict,
    "evaluation_targets":  dict,
    "metadata":            dict,
}

_VALID_DIFFICULTIES = {"easy", "middle", "difficult"}

_CATEGORY_LEVEL_2_REQUIRED = {
    "water_source_type", "contaminant_type", "effluent_use",
    "constraint_tags", "pollution_pattern",
}

_INPUT_DATA_REQUIRED = {"scenario_background", "water_quality",
                         "treatment_goal", "engineering_constraints"}

_CONSTRAINT_FIT_KEYS = {"cost_fit", "energy_fit", "operation_fit", "residuals_fit"}
_VALID_FIT_VALUES    = {
    "good", "medium_good", "medium", "medium_poor", "poor",
    "medium_to_high",  # allow reasonable variants
}

_REC_REQUIRED_FIELDS = {
    "rank", "process_chain", "core_unit_functions",
    "applicability_rationale", "constraint_fit",
    "potential_risks", "evidence_list",
}

_EVAL_TARGET_REQUIRED = {
    "top_k_quality", "constraint_consistency", "explanation_grounding",
}

_METADATA_REQUIRED = {"difficulty", "benchmark_split", "language", "case_source_type"}


def validate(json_text: str, expected_difficulty: Optional[str] = None) -> List[str]:
    """
    Validate the JSON string.

    Args:
        json_text           - raw JSON string produced by the LLM
        expected_difficulty - if provided, checks category_level_1 matches

    Returns:
        List of error description strings.  Empty list → valid.
    """
    errors: List[str] = []

    try:
        obj = json.loads(json_text)
    except json.JSONDecodeError as exc:
        return [f"JSON parse error: {exc}"]

    if not isinstance(obj, dict):
        return ["Root element must be a JSON object."]

    for field, expected_type in _TOP_LEVEL_REQUIRED.items():
        if field not in obj:
            errors.append(f"Missing top-level field: '{field}'")
        elif not isinstance(obj[field], expected_type):
            errors.append(
                f"Field '{field}' should be {expected_type.__name__}, "
                f"got {type(obj[field]).__name__}"
            )

    if errors:   # stop early if basics are missing
        return errors

    diff = obj["category_level_1"]
    if diff not in _VALID_DIFFICULTIES:
        errors.append(f"category_level_1 must be one of {_VALID_DIFFICULTIES}, got '{diff}'")
    if expected_difficulty and diff != expected_difficulty:
        errors.append(
            f"category_level_1 is '{diff}' but expected '{expected_difficulty}'"
        )

    cl2 = obj["category_level_2"]
    for key in _CATEGORY_LEVEL_2_REQUIRED:
        if key not in cl2:
            errors.append(f"category_level_2 missing key: '{key}'")
    if "contaminant_type" in cl2 and not isinstance(cl2["contaminant_type"], list):
        errors.append("category_level_2.contaminant_type must be a list")
    if "constraint_tags" in cl2 and not isinstance(cl2["constraint_tags"], list):
        errors.append("category_level_2.constraint_tags must be a list")

    inp = obj["input_data"]
    for key in _INPUT_DATA_REQUIRED:
        if key not in inp:
            errors.append(f"input_data missing key: '{key}'")

    eof = obj["expected_output_format"]
    if eof.get("top_k") != 5:
        errors.append(f"expected_output_format.top_k must be 5, got {eof.get('top_k')}")

    ra = obj["reference_answer"]
    recs = ra.get("ranked_recommendations")
    if not isinstance(recs, list):
        errors.append("reference_answer.ranked_recommendations must be a list")
        return errors  # can't validate further without the list

    if len(recs) != 5:
        errors.append(
            f"ranked_recommendations must have exactly 5 entries, got {len(recs)}"
        )

    for i, rec in enumerate(recs, 1):
        if not isinstance(rec, dict):
            errors.append(f"Recommendation #{i} must be a dict")
            continue

        # Required fields
        for rf in _REC_REQUIRED_FIELDS:
            if rf not in rec:
                errors.append(f"Recommendation #{i} missing field: '{rf}'")

        # process_chain must be non-empty list of strings
        pc = rec.get("process_chain", [])
        if not isinstance(pc, list) or len(pc) == 0:
            errors.append(f"Recommendation #{i} process_chain must be a non-empty list")

        # core_unit_functions must be a dict
        cuf = rec.get("core_unit_functions")
        if cuf is not None and not isinstance(cuf, dict):
            errors.append(f"Recommendation #{i} core_unit_functions must be a dict")

        # applicability_rationale – list
        ar = rec.get("applicability_rationale", [])
        if not isinstance(ar, list) or len(ar) == 0:
            errors.append(f"Recommendation #{i} applicability_rationale must be a non-empty list")

        # constraint_fit
        cf = rec.get("constraint_fit", {})
        if not isinstance(cf, dict):
            errors.append(f"Recommendation #{i} constraint_fit must be a dict")
        else:
            for k in _CONSTRAINT_FIT_KEYS:
                if k not in cf:
                    errors.append(f"Recommendation #{i} constraint_fit missing key: '{k}'")
                elif cf[k] not in _VALID_FIT_VALUES:
                    errors.append(
                        f"Recommendation #{i} constraint_fit.{k} invalid value: '{cf[k]}'"
                    )

        # potential_risks – list
        if not isinstance(rec.get("potential_risks"), list):
            errors.append(f"Recommendation #{i} potential_risks must be a list")

        # evidence_list – list
        if not isinstance(rec.get("evidence_list"), list):
            errors.append(f"Recommendation #{i} evidence_list must be a list")

        # rank value matches position
        if rec.get("rank") != i:
            errors.append(f"Recommendation #{i} has rank={rec.get('rank')} (expected {i})")

    et = obj["evaluation_targets"]
    for key in _EVAL_TARGET_REQUIRED:
        if key not in et:
            errors.append(f"evaluation_targets missing key: '{key}'")

    meta = obj["metadata"]
    for key in _METADATA_REQUIRED:
        if key not in meta:
            errors.append(f"metadata missing key: '{key}'")
    if meta.get("difficulty") != diff:
        errors.append(
            f"metadata.difficulty ('{meta.get('difficulty')}') "
            f"doesn't match category_level_1 ('{diff}')"
        )

    return errors


def errors_to_feedback(errors: List[str]) -> str:
    """Format error list as a concise feedback string for the LLM."""
    return "Validation errors found:\n" + "\n".join(f"  - {e}" for e in errors)
