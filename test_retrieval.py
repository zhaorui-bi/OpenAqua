#!/usr/bin/env python3
"""
Evaluate retrieval outputs on a directory of WContBench benchmark cases.

This script computes average Precision@k, Recall@k, and Hit@k across all JSON
benchmark files in a folder.

Benchmark assumptions:
- Each benchmark case is stored as one JSON file.
- The gold relevant evidence set is derived from:
  reference_answer.candidate_solutions[*].evidence_list

Prediction assumptions:
- Predictions are loaded from one JSON file.
- The script supports several common formats. Each prediction entry must include
  a case identifier and a ranked retrieval result list.

Supported prediction entry examples:

{
  "case_id": "WContBench_E_001",
  "retrieved_items": [
    "public_case_reports_on_iron_media_for_arsenic",
    "alternative_groundwater_treatment_case_examples"
  ]
}

{
  "case_id": "WContBench_E_001",
  "results": [
    {"id": "public_case_reports_on_iron_media_for_arsenic", "score": 0.91},
    {"doc_id": "alternative_groundwater_treatment_case_examples", "score": 0.78}
  ]
}

{
  "predictions": [
    ...
  ]
}
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple


CASE_ID_KEYS = ("case_id", "id", "case", "query_id")
RANKED_LIST_KEYS = (
    "retrieved_items",
    "retrieved_results",
    "retrieval_results",
    "results",
    "items",
    "topk",
    "top_k",
    "documents",
    "docs",
    "evidence",
    "evidence_list",
    "knowledge_items",
)
ITEM_ID_KEYS = (
    "id",
    "doc_id",
    "document_id",
    "item_id",
    "evidence_id",
    "knowledge_id",
    "key",
    "name",
    "title",
    "text",
    "content",
)


def normalize_text(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def unique_preserve_order(values: Iterable[str]) -> List[str]:
    seen: Set[str] = set()
    output: List[str] = []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            output.append(value)
    return output


def parse_k_values(raw_k: str) -> List[int]:
    values: List[int] = []
    for token in raw_k.split(","):
        token = token.strip()
        if not token:
            continue
        k = int(token)
        if k <= 0:
            raise ValueError("All k values must be positive integers.")
        values.append(k)
    if not values:
        raise ValueError("At least one k value must be provided.")
    return unique_preserve_order([str(v) for v in values])  # type: ignore[return-value]


def load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def extract_case_id(obj: Dict[str, Any], fallback: Optional[str] = None) -> str:
    for key in CASE_ID_KEYS:
        value = obj.get(key)
        if value is not None:
            return normalize_text(value)
    if fallback:
        return fallback
    raise ValueError("Could not determine case_id from benchmark or prediction entry.")


def extract_gold_evidence(case_data: Dict[str, Any]) -> List[str]:
    reference_answer = case_data.get("reference_answer", {})
    candidate_solutions = reference_answer.get("candidate_solutions", [])
    evidence_items: List[str] = []

    if isinstance(candidate_solutions, list):
        for solution in candidate_solutions:
            if not isinstance(solution, dict):
                continue
            evidence_list = solution.get("evidence_list", [])
            if isinstance(evidence_list, list):
                evidence_items.extend(normalize_text(x) for x in evidence_list)

    return unique_preserve_order(evidence_items)


def extract_ranked_items_from_sequence(seq: Sequence[Any]) -> List[str]:
    extracted: List[str] = []

    for item in seq:
        if isinstance(item, str):
            text = normalize_text(item)
            if text:
                extracted.append(text)
            continue

        if isinstance(item, dict):
            found_value: Optional[str] = None
            for key in ITEM_ID_KEYS:
                if key in item and item[key] is not None:
                    found_value = normalize_text(item[key])
                    if found_value:
                        break
            if found_value:
                extracted.append(found_value)
                continue

            if len(item) == 1:
                only_value = next(iter(item.values()))
                if only_value is not None:
                    text = normalize_text(only_value)
                    if text:
                        extracted.append(text)
                        continue

        text = normalize_text(item)
        if text:
            extracted.append(text)

    return extracted


def extract_ranked_items(pred_entry: Dict[str, Any]) -> List[str]:
    for key in RANKED_LIST_KEYS:
        if key not in pred_entry:
            continue
        value = pred_entry[key]
        if isinstance(value, list):
            return unique_preserve_order(extract_ranked_items_from_sequence(value))

    raise ValueError(
        "Could not find a ranked retrieval list in prediction entry. "
        f"Tried keys: {', '.join(RANKED_LIST_KEYS)}"
    )


def load_benchmark_cases(benchmark_dir: Path) -> Dict[str, Dict[str, Any]]:
    if not benchmark_dir.exists() or not benchmark_dir.is_dir():
        raise FileNotFoundError(f"Benchmark directory not found: {benchmark_dir}")

    cases: Dict[str, Dict[str, Any]] = {}
    json_files = sorted(benchmark_dir.glob("*.json"))

    if not json_files:
        raise FileNotFoundError(f"No JSON benchmark files found in: {benchmark_dir}")

    for path in json_files:
        data = load_json(path)
        if not isinstance(data, dict):
            continue
        if "reference_answer" not in data:
            continue

        fallback_case_id = path.stem
        case_id = extract_case_id(data, fallback=fallback_case_id)
        gold_evidence = extract_gold_evidence(data)

        cases[case_id] = {
            "case_id": case_id,
            "file_name": path.name,
            "gold_evidence": gold_evidence,
        }

    if not cases:
        raise ValueError(
            "No valid benchmark cases were found. Each benchmark JSON file must contain a reference_answer field."
        )

    return cases


def load_predictions(predictions_path: Path) -> Dict[str, List[str]]:
    raw = load_json(predictions_path)

    entries: List[Dict[str, Any]]
    if isinstance(raw, dict) and "predictions" in raw and isinstance(raw["predictions"], list):
        entries = raw["predictions"]
    elif isinstance(raw, list):
        entries = raw
    elif isinstance(raw, dict):
        entries = [raw]
    else:
        raise ValueError("Predictions file must be a JSON object or a JSON array.")

    parsed: Dict[str, List[str]] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        case_id = extract_case_id(entry)
        ranked_items = extract_ranked_items(entry)
        parsed[case_id] = ranked_items

    return parsed


def precision_at_k(retrieved_top_k: Sequence[str], gold_set: Set[str], k: int) -> float:
    if k <= 0:
        return 0.0
    hits = sum(1 for item in retrieved_top_k[:k] if item in gold_set)
    return hits / float(k)


def recall_at_k(retrieved_top_k: Sequence[str], gold_set: Set[str], k: int) -> float:
    if not gold_set:
        return 0.0
    hits = sum(1 for item in retrieved_top_k[:k] if item in gold_set)
    return hits / float(len(gold_set))


def hit_at_k(retrieved_top_k: Sequence[str], gold_set: Set[str], k: int) -> float:
    return 1.0 if any(item in gold_set for item in retrieved_top_k[:k]) else 0.0


def evaluate_case(case_id: str, gold_items: Sequence[str], predicted_items: Sequence[str], k: int) -> Dict[str, Any]:
    gold_set = set(gold_items)
    top_k_items = list(predicted_items[:k])
    intersection = [item for item in top_k_items if item in gold_set]

    return {
        "case_id": case_id,
        "k": k,
        "gold_count": len(gold_set),
        "retrieved_count_at_k": min(k, len(predicted_items)),
        "matched_items": unique_preserve_order(intersection),
        "precision_at_k": precision_at_k(predicted_items, gold_set, k),
        "recall_at_k": recall_at_k(predicted_items, gold_set, k),
        "hit_at_k": hit_at_k(predicted_items, gold_set, k),
    }


def evaluate_all_cases(
    benchmark_cases: Dict[str, Dict[str, Any]],
    predictions: Dict[str, List[str]],
    k_values: Sequence[int],
) -> Dict[str, Any]:
    benchmark_case_ids = sorted(benchmark_cases.keys())
    predicted_case_ids = set(predictions.keys())

    scored_case_ids = [case_id for case_id in benchmark_case_ids if case_id in predicted_case_ids]
    missing_prediction_case_ids = [case_id for case_id in benchmark_case_ids if case_id not in predicted_case_ids]
    extra_prediction_case_ids = sorted(predicted_case_ids - set(benchmark_case_ids))

    summary_by_k: Dict[str, Dict[str, Any]] = {}
    case_details_by_k: Dict[str, List[Dict[str, Any]]] = {}

    for k in k_values:
        per_case_results: List[Dict[str, Any]] = []

        for case_id in scored_case_ids:
            case_info = benchmark_cases[case_id]
            gold_items = case_info["gold_evidence"]
            predicted_items = predictions[case_id]
            per_case_results.append(evaluate_case(case_id, gold_items, predicted_items, k))

        if per_case_results:
            avg_precision = sum(x["precision_at_k"] for x in per_case_results) / len(per_case_results)
            avg_recall = sum(x["recall_at_k"] for x in per_case_results) / len(per_case_results)
            avg_hit = sum(x["hit_at_k"] for x in per_case_results) / len(per_case_results)
        else:
            avg_precision = 0.0
            avg_recall = 0.0
            avg_hit = 0.0

        summary_by_k[str(k)] = {
            "precision_at_k": avg_precision,
            "recall_at_k": avg_recall,
            "hit_at_k": avg_hit,
            "n_scored_cases": len(per_case_results),
        }
        case_details_by_k[str(k)] = per_case_results

    return {
        "n_benchmark_cases": len(benchmark_case_ids),
        "n_prediction_cases": len(predictions),
        "n_scored_cases": len(scored_case_ids),
        "n_missing_predictions": len(missing_prediction_case_ids),
        "missing_predictions": missing_prediction_case_ids,
        "extra_predictions": extra_prediction_case_ids,
        "results_by_k": summary_by_k,
        "case_details_by_k": case_details_by_k,
    }


def build_example_predictions(benchmark_cases: Dict[str, Dict[str, Any]], output_path: Path) -> None:
    example_entries: List[Dict[str, Any]] = []

    for case_id in sorted(benchmark_cases.keys()):
        gold = benchmark_cases[case_id]["gold_evidence"]
        example_items = list(gold[:2])
        if "dummy_non_relevant_item" not in example_items:
            example_items.append("dummy_non_relevant_item")
        example_entries.append(
            {
                "case_id": case_id,
                "retrieved_items": example_items,
            }
        )

    payload = {"predictions": example_entries}
    with output_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)


def format_float(value: float) -> str:
    return f"{value:.6f}"


def print_summary(results: Dict[str, Any]) -> None:
    print(f"Benchmark cases: {results['n_benchmark_cases']}")
    print(f"Prediction cases: {results['n_prediction_cases']}")
    print(f"Scored cases: {results['n_scored_cases']}")
    print(f"Missing predictions: {results['n_missing_predictions']}")

    if results["missing_predictions"]:
        print("Missing prediction case_ids:")
        for case_id in results["missing_predictions"]:
            print(f"  - {case_id}")

    if results["extra_predictions"]:
        print("Extra prediction case_ids:")
        for case_id in results["extra_predictions"]:
            print(f"  - {case_id}")

    print("")
    for k_str, metrics in results["results_by_k"].items():
        print(f"k = {k_str}")
        print(f"  Precision@{k_str}: {format_float(metrics['precision_at_k'])}")
        print(f"  Recall@{k_str}:    {format_float(metrics['recall_at_k'])}")
        print(f"  Hit@{k_str}:       {format_float(metrics['hit_at_k'])}")
        print("")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate retrieval outputs on a directory of WContBench JSON benchmark files."
    )
    parser.add_argument(
        "--benchmark-dir",
        type=Path,
        required=True,
        help="Directory containing benchmark JSON files.",
    )
    parser.add_argument(
        "--predictions",
        type=Path,
        help="Path to retrieval prediction JSON file.",
    )
    parser.add_argument(
        "--k",
        type=str,
        default="1,3,5",
        help="Comma-separated list of k values, for example: 1,3,5,10",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path to save evaluation results as JSON.",
    )
    parser.add_argument(
        "--write-example-predictions",
        type=Path,
        help="Write an example predictions file and exit.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    benchmark_cases = load_benchmark_cases(args.benchmark_dir)

    if args.write_example_predictions:
        build_example_predictions(benchmark_cases, args.write_example_predictions)
        print(f"Example predictions written to: {args.write_example_predictions}")
        return

    if args.predictions is None:
        raise ValueError("--predictions is required unless --write-example-predictions is used.")

    k_values = [int(x) for x in parse_k_values(args.k)]
    predictions = load_predictions(args.predictions)
    results = evaluate_all_cases(benchmark_cases, predictions, k_values)

    print_summary(results)

    if args.output:
        with args.output.open("w", encoding="utf-8") as f:
            json.dump(results, f, ensure_ascii=False, indent=2)
        print(f"Results written to: {args.output}")


if __name__ == "__main__":
    main()
