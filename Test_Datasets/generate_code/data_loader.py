"""
data_loader.py
--------------
Loads all knowledge sources:
  1. Taxonomy   - canonical contaminant names + synonym map
  2. KB Cases   - case-level real-world EPA reference cases
  3. Few-shot   - existing benchmark JSON examples
"""

import json
import os
from collections import defaultdict
from functools import lru_cache
from typing import Dict, List, Tuple

import config


def load_taxonomy() -> Tuple[List[str], Dict[str, List[str]]]:
    """
    Returns:
        unique_names  - deduplicated list of canonical contaminant names
        synonym_map   - {canonical_name: [synonym1, synonym2, ...]}
    """
    with open(config.TAXONOMY_PATH, encoding="utf-8") as f:
        raw = json.load(f)

    synonym_map: Dict[str, List[str]] = defaultdict(list)
    for entry in raw:
        name = entry["Contaminant Name"].strip()
        syn  = entry.get("Synonyms", "").strip()
        if syn and syn != name:
            synonym_map[name].append(syn)

    unique_names = list(synonym_map.keys())
    return unique_names, dict(synonym_map)




def load_kb_cases() -> List[dict]:
    """Load all EPA case-level reference cases from kb_cases.json."""
    with open(config.KB_CASES_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data.get("cases", [])


def find_relevant_kb_cases(contaminants: List[str], kb_cases: List[dict], top_k: int = 3) -> List[dict]:
    """
    Return the top_k KB cases most relevant to the given contaminant list.
    Relevance = number of matching contaminant tokens (case-insensitive).
    """
    query_tokens = {c.lower() for c in contaminants}
    # Also add first-word tokens (e.g. "PFAS" matches "PFOA", "PFOS")
    short_tokens = {c.split()[0].lower() for c in contaminants}

    scored = []
    for case in kb_cases:
        case_contams = [str(x).lower() for x in case.get("contaminants", [])]
        score = sum(
            1 for cc in case_contams
            if any(qt in cc or cc in qt for qt in query_tokens | short_tokens)
        )
        if score > 0:
            scored.append((score, case))

    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored[:top_k]]


def format_kb_cases_text(cases: List[dict]) -> str:
    """Format KB cases as concise reference text for LLM prompts."""
    if not cases:
        return ""
    lines = ["=== Real-world reference cases (for evidence grounding) ==="]
    for c in cases:
        lines.append(
            f"[{c['case_id']}] {c['title']}\n"
            f"  Source water: {c.get('source_water', 'N/A')} | "
            f"Contaminants: {', '.join(c.get('contaminants', []))}\n"
            f"  Treatment chain: {' → '.join(c.get('treatment_chain', []))}\n"
            f"  Outcome: {c.get('outcome', '')[:200]}"
        )
    return "\n".join(lines)




@lru_cache(maxsize=3)
def load_few_shot_example(difficulty: str) -> str:
    """Return the raw JSON string of the seed example for a given difficulty."""
    path = config.FEW_SHOT_PATHS.get(difficulty)
    if path and os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read()
    return ""
