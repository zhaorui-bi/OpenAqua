#!/usr/bin/env python3
"""Evaluate OpenAqua treatment-chain outputs on a WContBench benchmark folder.

This script computes:
- Precision
- Recall
- F1-score
- Coverage Rate
- Hit Rate
- Case-level Acceptability (CLA)

Evaluation logic:
1) It does not require exact full-chain matching.
2) It compares predicted process units with the reference case's key treatment units.
3) It averages metrics across all benchmark JSON files in a directory.
4) CLA is a case-level engineering reasonableness check.
"""

from __future__ import annotations

import argparse
import json
import pathlib
import re
from collections import Counter
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Sequence, Set, Tuple


CANONICAL_SYNONYMS: Dict[str, Set[str]] = {
    "oxidation": {
        "oxidation",
        "pre_oxidation",
        "chemical_oxidation",
        "oxidative_conversion",
        "aeration_oxidation",
        "oxidation_step",
    },
    "coagulation": {
        "coagulation",
        "coagulate",
        "flocculation",
        "coagulation_flocculation",
        "chemical_coagulation",
    },
    "adsorption": {
        "adsorption",
        "adsorptive_media",
        "adsorptive_medium",
        "iron_based_adsorptive_media",
        "activated_alumina",
        "ferric_media",
        "media_adsorption",
    },
    "coagulation_or_adsorptive_media": {
        "coagulation_or_adsorptive_media",
    },
    "sedimentation": {
        "sedimentation",
        "clarification",
        "settling",
        "solid_liquid_separation",
        "gravity_settling",
    },
    "filtration": {
        "filtration",
        "sand_filtration",
        "rapid_sand_filtration",
        "multimedia_filtration",
        "post_filtration",
        "filter",
        "polishing_filtration",
    },
    "disinfection": {
        "disinfection",
        "chlorination",
        "uv",
        "ultraviolet_disinfection",
        "chloramine",
        "final_disinfection",
    },
    "ion_exchange": {
        "ion_exchange",
        "anion_exchange",
        "exchange_resin",
        "resin_exchange",
    },
    "membrane": {
        "nanofiltration_or_reverse_osmosis",
        "reverse_osmosis",
        "ro",
        "nanofiltration",
        "nf",
        "membrane",
        "high_pressure_membrane",
    },
    "stabilization": {
        "stabilization",
        "remineralization",
        "ph_adjustment",
        "post_stabilization",
    },
}

FORBIDDEN_FIRST_RANK_UNITS: Set[str] = {"membrane"}
REMOVAL_DIRECTION_UNITS: Set[str] = {
    "coagulation",
    "adsorption",
    "coagulation_or_adsorptive_media",
    "ion_exchange",
    "membrane",
}


@dataclass
class CaseMetrics:
    case_id: str
    predicted_units: List[str]
    reference_units: List[str]
    matched_units: List[str]
    precision: float
    recall: float
    f1: float
    coverage: float
    hit: int
    cla: int
    acceptability_reasons: List[str]


def _slug(text: str) -> str:
    text = str(text).strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return text.strip("_")


def normalize_unit(unit: str) -> str:
    slug = _slug(unit)
    for canonical, variants in CANONICAL_SYNONYMS.items():
        if slug == canonical or slug in variants:
            return canonical

    if "oxid" in slug:
        return "oxidation"
    if "coagul" in slug or "floc" in slug:
        return "coagulation"
    if "adsorp" in slug or "media" in slug:
        return "adsorption"
    if "sediment" in slug or "clarif" in slug or "sett" in slug:
        return "sedimentation"
    if "filtrat" in slug or slug.endswith("filter"):
        return "filtration"
    if "disinfect" in slug or "chlor" in slug or slug == "uv":
        return "disinfection"
    if "ion_exchange" in slug or ("exchange" in slug and "ion" in slug):
        return "ion_exchange"
    if "osmosis" in slug or slug in {"ro", "nf"} or "membrane" in slug or "nanofiltration" in slug:
        return "membrane"
    if "stabil" in slug or "remineral" in slug or "ph_adjust" in slug:
        return "stabilization"

    return slug


def normalize_chain(units: Sequence[str]) -> List[str]:
    return [normalize_unit(u) for u in units if str(u).strip()]


def dedupe_keep_order(items: Sequence[str]) -> List[str]:
    seen: Set[str] = set()
    out: List[str] = []
    for item in items:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out


def safe_div(numerator: float, denominator: float) -> float:
    return numerator / denominator if denominator else 0.0


def f1_score(precision: float, recall: float) -> float:
    denom = precision + recall
    return 0.0 if denom == 0 else 2 * precision * recall / denom


def load_json_or_jsonl(path: pathlib.Path) -> Any:
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        raise ValueError(f"Empty file: {path}")

    if text.startswith("{") or text.startswith("["):
        return json.loads(text)

    rows = []
    for line in text.splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows


def parse_predictions(obj: Any) -> List[Dict[str, Any]]:
    if isinstance(obj, list):
        return obj
    if isinstance(obj, dict):
        if "predictions" in obj and isinstance(obj["predictions"], list):
            return obj["predictions"]
        if "case_id" in obj and "process_chain" in obj:
            return [obj]
        rows = []
        for case_id, payload in obj.items():
            if isinstance(payload, dict):
                row = dict(payload)
                row.setdefault("case_id", case_id)
                rows.append(row)
        if rows:
            return rows
    raise ValueError("Unsupported prediction file format.")


def parse_prediction_chain(pred: Dict[str, Any]) -> List[str]:
    chain = pred.get("process_chain")
    if chain is None:
        ranked = pred.get("ranked_recommendations") or pred.get("recommendations")
        if ranked and isinstance(ranked, list) and isinstance(ranked[0], dict):
            chain = ranked[0].get("process_chain", [])
    if not isinstance(chain, list):
        raise ValueError(f"Prediction for case {pred.get('case_id', '<unknown>')} does not contain a valid process_chain list.")
    return chain


def load_benchmark_cases(benchmark_dir: pathlib.Path) -> Dict[str, Dict[str, Any]]:
    if not benchmark_dir.exists() or not benchmark_dir.is_dir():
        raise ValueError(f"Benchmark path is not a directory: {benchmark_dir}")

    cases: Dict[str, Dict[str, Any]] = {}
    for path in sorted(benchmark_dir.glob("*.json")):
        obj = load_json_or_jsonl(path)
        if not isinstance(obj, dict) or "case_id" not in obj:
            continue
        case_id = str(obj["case_id"])
        obj["_source_file"] = str(path)
        cases[case_id] = obj

    if not cases:
        raise ValueError(f"No valid benchmark case JSON files found in: {benchmark_dir}")
    return cases


def extract_reference_units(case_data: Dict[str, Any]) -> Tuple[List[str], Set[str]]:
    recs = case_data["reference_answer"]["ranked_recommendations"]
    all_units: List[str] = []
    for rec in recs:
        all_units.extend(normalize_chain(rec.get("process_chain", [])))

    freq = Counter(all_units)
    ordered = [unit for unit, _ in freq.most_common()]
    reference_units = dedupe_keep_order(ordered)
    required_units = set(normalize_chain(recs[0].get("process_chain", [])))
    return reference_units, required_units


def check_case_acceptability(
    predicted_units: Sequence[str],
    matched_units: Set[str],
    required_units: Set[str],
    case_data: Dict[str, Any],
) -> Tuple[int, List[str]]:
    reasons: List[str] = []
    predicted = list(predicted_units)
    pred_set = set(predicted)

    if matched_units:
        reasons.append("At least one reference key unit is matched.")
    else:
        reasons.append("No reference key unit is matched.")
        return 0, reasons

    species = (
        case_data.get("input_data", {})
        .get("water_quality", {})
        .get("arsenic_dominant_species", "")
        .lower()
    )
    if "as(iii)" in species and "oxidation" not in pred_set:
        reasons.append("The case includes As(III), but the prediction misses oxidation pretreatment.")
        return 0, reasons

    if not (pred_set & REMOVAL_DIRECTION_UNITS):
        reasons.append("No core contaminant-removal unit is included.")
        return 0, reasons

    if pred_set & {"coagulation", "adsorption", "coagulation_or_adsorptive_media"} and "filtration" not in pred_set:
        reasons.append("A coagulation or adsorption route is present without filtration polishing.")
        return 0, reasons

    constraints = case_data.get("input_data", {}).get("engineering_constraints", {})
    capex = str(constraints.get("capex_level", "")).lower()
    energy = str(constraints.get("energy_constraint", "")).lower()
    complexity = str(constraints.get("operation_complexity", "")).lower()
    if predicted and predicted[0] in FORBIDDEN_FIRST_RANK_UNITS and (
        capex in {"medium", "low"} or energy in {"medium", "low"} or "low_to_medium" in complexity
    ):
        reasons.append("A membrane-first route conflicts with the stated cost, energy, or operation constraints.")
        return 0, reasons

    if pred_set <= {"membrane", "stabilization", "disinfection"}:
        reasons.append("The route is overly dominated by a high-intensity membrane pathway.")
        return 0, reasons

    required_hits = len(pred_set & required_units)
    if required_hits < 2:
        reasons.append("Coverage of the primary reference direction is insufficient.")
        return 0, reasons

    reasons.append("No obvious violation of treatment logic or case constraints is found.")
    return 1, reasons


def score_case(case_id: str, predicted_chain: Sequence[str], case_data: Dict[str, Any]) -> CaseMetrics:
    reference_units, required_units = extract_reference_units(case_data)
    predicted_units = dedupe_keep_order(normalize_chain(predicted_chain))
    reference_units = dedupe_keep_order(reference_units)

    matched_units = set(predicted_units) & set(reference_units)
    precision = safe_div(len(matched_units), len(predicted_units))
    recall = safe_div(len(matched_units), len(reference_units))
    f1 = f1_score(precision, recall)
    coverage = recall
    hit = int(bool(matched_units))
    cla, reasons = check_case_acceptability(predicted_units, matched_units, required_units, case_data)

    return CaseMetrics(
        case_id=case_id,
        predicted_units=predicted_units,
        reference_units=reference_units,
        matched_units=sorted(matched_units),
        precision=precision,
        recall=recall,
        f1=f1,
        coverage=coverage,
        hit=hit,
        cla=cla,
        acceptability_reasons=reasons,
    )


def aggregate_metrics(case_metrics: Sequence[CaseMetrics]) -> Dict[str, Any]:
    n_cases = len(case_metrics)
    if n_cases == 0:
        raise ValueError("No cases were evaluated.")

    return {
        "n_cases": n_cases,
        "macro_precision": sum(cm.precision for cm in case_metrics) / n_cases,
        "macro_recall": sum(cm.recall for cm in case_metrics) / n_cases,
        "macro_f1": sum(cm.f1 for cm in case_metrics) / n_cases,
        "coverage_rate": sum(cm.coverage for cm in case_metrics) / n_cases,
        "hit_rate": sum(cm.hit for cm in case_metrics) / n_cases,
        "case_level_acceptability": sum(cm.cla for cm in case_metrics) / n_cases,
    }


def evaluate_predictions(benchmark_dir: pathlib.Path, prediction_path: pathlib.Path) -> Dict[str, Any]:
    benchmark_cases = load_benchmark_cases(benchmark_dir)
    predictions_raw = load_json_or_jsonl(prediction_path)
    predictions = parse_predictions(predictions_raw)
    prediction_map = {str(pred["case_id"]): pred for pred in predictions if "case_id" in pred}

    case_metrics: List[CaseMetrics] = []
    missing_predictions: List[str] = []

    for case_id, case_data in benchmark_cases.items():
        pred = prediction_map.get(case_id)
        if pred is None:
            missing_predictions.append(case_id)
            continue
        chain = parse_prediction_chain(pred)
        case_metrics.append(score_case(case_id, chain, case_data))

    summary = aggregate_metrics(case_metrics)
    summary["n_benchmark_cases"] = len(benchmark_cases)
    summary["n_scored_cases"] = len(case_metrics)
    summary["n_missing_predictions"] = len(missing_predictions)

    return {
        "summary": summary,
        "missing_predictions": missing_predictions,
        "cases": [asdict(cm) for cm in case_metrics],
    }


def build_example_prediction_file(path: pathlib.Path) -> None:
    sample = {
        "predictions": [
            {
                "case_id": "WContBench_E_001",
                "process_chain": [
                    "oxidation",
                    "iron_based_adsorptive_media",
                    "post_filtration",
                    "disinfection",
                ],
            }
        ]
    }
    path.write_text(json.dumps(sample, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Evaluate OpenAqua outputs on a WContBench benchmark directory.")
    parser.add_argument(
        "--benchmark-dir",
        type=pathlib.Path,
        help="Path to a directory containing benchmark case JSON files.",
    )
    parser.add_argument(
        "--predictions",
        type=pathlib.Path,
        help="Path to prediction JSON or JSONL.",
    )
    parser.add_argument(
        "--output",
        type=pathlib.Path,
        help="Optional path to save evaluation results as JSON.",
    )
    parser.add_argument(
        "--write-example-predictions",
        type=pathlib.Path,
        help="Write an example prediction file and exit.",
    )
    args = parser.parse_args()

    if args.write_example_predictions:
        build_example_prediction_file(args.write_example_predictions)
        print(f"Wrote example predictions to: {args.write_example_predictions}")
        return

    if not args.benchmark_dir:
        parser.error("--benchmark-dir is required unless --write-example-predictions is used.")
    if not args.predictions:
        parser.error("--predictions is required unless --write-example-predictions is used.")

    results = evaluate_predictions(args.benchmark_dir, args.predictions)
    rendered = json.dumps(results, ensure_ascii=False, indent=2)
    print(rendered)

    if args.output:
        args.output.write_text(rendered, encoding="utf-8")


if __name__ == "__main__":
    main()
