"""
prompt_builder.py
-----------------
Builds the full LLM prompt for each CaseSpec by combining:
  1. System prompt (expert persona + task framing)
  2. Knowledge injection (TDB unit-level + KB case-level)
  3. Few-shot example (one seed case at same difficulty)
  4. Case spec instructions (what to generate)
  5. JSON schema template
  6. Output constraint (JSON only)

Difficulty-specific nuances ensure the LLM produces correctly-
characterised cases at each level.
"""

from typing import List, Optional

import data_loader
from contaminant_planner import CaseSpec


_DIFF_INSTRUCTIONS = {
    "easy": """\
DIFFICULTY: Easy - Explicit Goal Type
The case must present a CLEAR, WELL-DEFINED scenario where:
- Water source type, target pollutant(s), and effluent use are unambiguous.
- Engineering constraints (cost, energy, O&M) are moderate and stated clearly.
- The task is to select the best-supported process chain from established knowledge.
- Ranked recommendations should flow naturally from the constraints; the top option
  should be clearly justified by conventional or proven technology.
- Avoid artificial complexity or missing data.""",

    "middle": """\
DIFFICULTY: Middle - Multi-Constraint Trade-off Type
The case must present a scenario where:
- The answer is NOT simply "which technology removes the contaminant" but
  "which option best balances multiple competing constraints".
- At least two plausible treatment routes exist; the ranking depends on
  careful weighting of cost, O&M complexity, residuals handling, and effluent limits.
- The scenario_background should make the trade-off tension explicit.
- Ranked recommendations should show how different constraints favour different options.
- Include at least one option that is technically capable but ranks lower due to
  constraint misalignment.""",

    "difficult": """\
DIFFICULTY: Difficult - Complex / Uncertain Type
The case must present a scenario where:
- Information is INCOMPLETE or conditions are AMBIGUOUS (e.g., fluctuating influent,
  partially characterised pollutant mix, co-occurring legacy and emerging contaminants).
- The challenge is not simply retrieving known facts but reasoning under uncertainty.
- The scenario_background should explicitly state what is unknown or variable.
- water_quality should include at least one field like "influent_variability": "high"
  or a note that certain contaminants are "suspected but not fully characterised".
- Ranked recommendations must include risk caveats and uncertainty flags.
- evaluation_targets.risk_awareness must be non-trivial and specific.""",
}


_JSON_SCHEMA = """\
{
  "case_id": "<CASE_ID>",
  "case_name": "<one-line descriptive title>",
  "category_level_1": "<easy|middle|difficult>",
  "category_level_2": {
    "water_source_type": "<source type string>",
    "contaminant_type": ["<contaminant1>", ...],
    "effluent_use": "<use type string>",
    "constraint_tags": ["<tag1>", "<tag2>", ...],
    "pollution_pattern": "<pattern string>"
  },
  "task_description": "<one-sentence task instruction>",
  "input_data": {
    "scenario_background": "<2-4 sentences describing the real-world scenario>",
    "water_quality": {
      "source_type": "<string>",
      "<param>_<unit>": <value>,
      ...
    },
    "treatment_goal": {
      "use_type": "<string>",
      "target_requirement": "<string>",
      "secondary_goals": ["<goal1>", ...]
    },
    "engineering_constraints": {
      "capex_level": "<low|medium_low|medium|medium_high|high>",
      "opex_level":  "<low|medium_low|medium|medium_high|high>",
      "energy_constraint": "<low|medium|medium_to_high_sensitivity|high>",
      "operation_complexity": "<low|low_to_medium|medium|high>",
      "residuals_management": "<string describing constraint>",
      "footprint_constraint": "<low|medium|high>",
      "robustness_requirement": "<string>"
    }
  },
  "expected_output_format": {
    "top_k": 5,
    "require_fields": [
      "rank", "process_chain", "core_unit_functions",
      "applicability_rationale", "constraint_fit",
      "potential_risks", "evidence_list"
    ]
  },
  "reference_answer": {
    "ranked_recommendations": [
      {
        "rank": 1,
        "process_chain": ["<step1>", "<step2>", ...],
        "core_unit_functions": {"<step1>": "<function>", ...},
        "applicability_rationale": ["<reason1>", ...],
        "constraint_fit": {
          "cost_fit": "<good|medium_good|medium|medium_poor|poor>",
          "energy_fit": "<good|medium_good|medium|medium_poor|poor>",
          "operation_fit": "<good|medium_good|medium|medium_poor|poor>",
          "residuals_fit": "<good|medium_good|medium|medium_poor|poor>"
        },
        "potential_risks": ["<risk1>", ...],
        "evidence_list": ["<evidence_reference_string1>", ...]
      }
      // ... ranks 2-5
    ]
  },
  "evaluation_targets": {
    "top_k_quality": {
      "preferred_rank_pattern": ["<pattern description1>", ...]
    },
    "constraint_consistency": {
      "must_reflect": ["<constraint reflection1>", ...]
    },
    "explanation_grounding": {
      "must_contain": ["<grounding requirement1>", ...]
    },
    "risk_awareness": {
      "should_mention": ["<risk topic1>", ...]
    }
  },
  "metadata": {
    "difficulty": "<easy|middle|difficult>",
    "benchmark_split": "test",
    "language": "en",
    "case_source_type": "synthetic_case_based_on_public_water_treatment_knowledge"
  }
}"""


_SYSTEM_PROMPT = """\
You are a senior water treatment engineer and benchmark dataset designer.
Your task is to generate a single, high-quality benchmark case in strict JSON format
for the WContBench water-treatment recommendation benchmark.

Rules:
1. Output ONLY a single valid JSON object - no markdown fences, no commentary.
2. The JSON must fully conform to the schema provided.
3. All contaminant values in water_quality must be realistic (use plausible mg/L or µg/L ranges).
4. ranked_recommendations must contain exactly 5 entries (rank 1-5).
5. evidence_list entries are descriptive strings referencing public guidance
   or case knowledge (e.g. "EPA_guidance_for_arsenic_removal_in_groundwater").
6. Use the case-level reference knowledge provided to ground the treatment choices.
7. Do not copy the few-shot example verbatim - create a distinct new scenario."""



def build_prompt(spec: CaseSpec, kb_cases: List[dict],
                 retry_feedback: Optional[str] = None) -> List[dict]:
    """
    Build the messages list for the OpenRouter chat completions API.

    Args:
        spec           - CaseSpec describing what to generate
        kb_cases       - all loaded KB cases (will filter relevant ones)
        retry_feedback - validation error string to prepend on retry

    Returns:
        [{"role": "system", "content": ...}, {"role": "user", "content": ...}]
    """
    relevant_cases = data_loader.find_relevant_kb_cases(spec.contaminants, kb_cases, top_k=3)
    kb_text = data_loader.format_kb_cases_text(relevant_cases)

    few_shot = data_loader.load_few_shot_example(spec.difficulty)

    alias_hint = ""
    if spec.use_alias_for:
        alias_hint = (
            f"\nNOTE: In the scenario_background and case_name, refer to "
            f"'{spec.contaminants[0]}' using the alias '{spec.use_alias_for}' "
            f"(keep canonical name in contaminant_type array)."
        )

    user_parts: List[str] = []

    # Difficulty instruction
    user_parts.append(_DIFF_INSTRUCTIONS[spec.difficulty])

    # KB case evidence
    if kb_text:
        user_parts.append("\n" + kb_text)

    # Few-shot example
    if few_shot:
        user_parts.append(
            "\n--- Few-shot example (same difficulty, DO NOT copy verbatim) ---\n"
            + few_shot
        )

    # Generation instruction
    contam_list = ", ".join(spec.contaminants)
    user_parts.append(f"""
--- Your task ---
Generate ONE benchmark case using EXACTLY the following parameters:
  case_id          : {spec.case_id}
  difficulty       : {spec.difficulty}
  contaminants     : {contam_list}
  water_source     : {spec.water_source}
  effluent_use     : {spec.effluent_use}
  constraint_tags  : {spec.constraint_tags}
  pollution_pattern: {spec.pollution_pattern}
{alias_hint}

Fill in all water_quality values with realistic numbers appropriate for this
source water type and contaminant combination.
""")

    # Schema
    user_parts.append("--- Required JSON schema ---\n" + _JSON_SCHEMA)

    # Retry feedback
    if retry_feedback:
        user_parts.append(
            f"\n--- PREVIOUS ATTEMPT FAILED VALIDATION ---\n"
            f"Fix these issues in your new attempt:\n{retry_feedback}"
        )

    user_parts.append("\nOutput ONLY valid JSON. No markdown. No explanation.")

    return [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user",   "content": "\n\n".join(user_parts)},
    ]
