"""
contaminant_planner.py
-----------------------
Produces the full list of 337 CaseSpec dictionaries that tell the
generator exactly which contaminant(s), water-source type, effluent use,
and constraint tags each case should use.

Coverage guarantee:
  - Every unique contaminant in taxonomy.json appears in at least one case.
  - A small number of cases use synonym names to exercise alias coverage.

Distribution:
  Easy      92   mostly single contaminant, clear goal
  Middle    117  1-3 contaminants, multi-constraint trade-off
  Difficult 128  2-5 contaminants, complex / uncertain / mixed
"""

import random
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import config
import data_loader


WATER_SOURCES = {
    "easy":      ["groundwater", "surface_water", "well_water"],
    "middle":    ["groundwater", "surface_water", "lake_water", "river_water",
                  "reservoir_water", "brackish_groundwater"],
    "difficult": ["industrial_wastewater", "municipal_wastewater",
                  "mixed_industrial_municipal", "stormwater_runoff",
                  "agricultural_drainage", "landfill_leachate",
                  "mine_drainage", "reclaimed_water_source"],
}

EFFLUENT_USES = {
    "easy":      ["drinking_water"],
    "middle":    ["drinking_water", "potable_reuse", "groundwater_recharge"],
    "difficult": ["industrial_reuse", "agricultural_reuse", "environmental_discharge",
                  "potable_reuse", "groundwater_recharge"],
}

CONSTRAINT_POOL = {
    "easy": [
        ["moderate_cost_constraint", "conventional_operation"],
        ["proven_technology_preference"],
        ["low_energy_constraint", "small_system"],
        ["moderate_cost_constraint", "stable_operation_required"],
        ["minimal_chemical_use"],
    ],
    "middle": [
        ["cost_constraint", "low_operation_complexity", "residuals_management_constraint"],
        ["strict_effluent_limit", "space_limitation", "moderate_cost_constraint"],
        ["high_water_recovery", "concentrate_handling_constraint"],
        ["multiple_contaminant_targets", "moderate_cost_constraint", "operator_skill_limited"],
        ["seasonal_variation", "cost_constraint", "energy_constraint"],
        ["strict_effluent_limit", "low_energy_preference", "chemical_minimization"],
        ["pilot_only_scale", "capital_constraint", "remote_location"],
    ],
    "difficult": [
        ["multi_objective", "mixed_pollution", "high_uncertainty", "cost_energy_tradeoff"],
        ["influent_variability", "unknown_trace_pollutants", "reuse_quality_required"],
        ["emergency_deployment", "rapid_scale_up", "mixed_contaminants"],
        ["regulatory_ambiguity", "co_occurring_pollutants", "limited_site_data"],
        ["industrial_shock_load", "brine_management_constraint", "membrane_fouling_risk"],
        ["incomplete_characterization", "multi_barrier_required", "cost_energy_tradeoff"],
        ["legacy_contamination", "evolving_standards", "mixed_organic_inorganic"],
    ],
}

POLLUTION_PATTERNS = {
    "easy":      ["single_contaminant", "primary_contaminant_with_matrix_effects"],
    "middle":    ["dual_contaminants", "primary_with_co_contaminants",
                  "emerging_contaminant", "regulated_contaminant_mix"],
    "difficult": ["complex_mixed_contaminants", "unknown_fraction_present",
                  "fluctuating_mixed_load", "co_occurring_legacy_and_emerging"],
}

# Number of contaminants per case by difficulty
CONTAM_COUNT_RANGE = {
    "easy":      (1, 1),
    "middle":    (1, 3),
    "difficult": (2, 5),
}




@dataclass
class CaseSpec:
    case_id:          str
    difficulty:       str
    contaminants:     List[str]          # canonical names (may include one alias)
    water_source:     str
    effluent_use:     str
    constraint_tags:  List[str]
    pollution_pattern: str
    use_alias_for:    Optional[str] = None  # if set, use this alias in scenario text



def build_case_specs(seed: int = 42) -> Dict[str, List[CaseSpec]]:
    """
    Returns {difficulty: [CaseSpec, ...]} covering all taxonomy contaminants.
    """
    rng = random.Random(seed)

    unique_names, synonym_map = data_loader.load_taxonomy()

    # Total new cases to generate per difficulty (excluding existing _001 seeds)
    targets = {d: cfg["total"] - 1 for d, cfg in config.GENERATION_TARGETS.items()}

    shuffled = rng.sample(unique_names, len(unique_names))

    # Assign each contaminant to exactly one difficulty slot proportionally
    n_total   = sum(targets.values())           # 334
    n_contams = len(shuffled)                   # ~69

    # How many to assign per difficulty (proportional to case count)
    first_pass: Dict[str, List[str]] = {"easy": [], "middle": [], "difficult": []}
    diffs = ["easy", "middle", "difficult"]
    for i, name in enumerate(shuffled):
        # Round-robin weighted by target ratios
        weights = [targets[d] for d in diffs]
        chosen  = rng.choices(diffs, weights=weights)[0]
        first_pass[chosen].append(name)

    specs: Dict[str, List[CaseSpec]] = {d: [] for d in diffs}

    for diff in diffs:
        needed = targets[diff]
        start  = config.GENERATION_TARGETS[diff]["start_idx"]
        prefix = {"easy": "E", "middle": "M", "difficult": "D"}[diff]

        assigned  = first_pass[diff]
        remaining = needed - len(assigned)

        # Fill extra slots by sampling from full pool (allow repeats for variety)
        extra_pool = shuffled if remaining <= len(shuffled) else shuffled * 3
        extras     = rng.choices(extra_pool, k=remaining)
        all_contams_for_diff = assigned + extras
        rng.shuffle(all_contams_for_diff)

        lo, hi = CONTAM_COUNT_RANGE[diff]

        for i, primary in enumerate(all_contams_for_diff):
            case_num = start + i
            case_id  = f"WContBench_{prefix}_{case_num:03d}"

            # Build contaminant list for this case
            n_contams_this = rng.randint(lo, hi)
            if n_contams_this == 1:
                contams = [primary]
            else:
                others = rng.sample(
                    [c for c in shuffled if c != primary],
                    k=min(n_contams_this - 1, len(shuffled) - 1),
                )
                contams = [primary] + others

            # Occasionally substitute one synonym to exercise alias coverage
            use_alias = None
            syns = synonym_map.get(primary, [])
            if syns and rng.random() < 0.15:   # ~15% of cases use alias
                use_alias = rng.choice(syns)

            specs[diff].append(CaseSpec(
                case_id          = case_id,
                difficulty       = diff,
                contaminants     = contams,
                water_source     = rng.choice(WATER_SOURCES[diff]),
                effluent_use     = rng.choice(EFFLUENT_USES[diff]),
                constraint_tags  = rng.choice(CONSTRAINT_POOL[diff]),
                pollution_pattern= rng.choice(POLLUTION_PATTERNS[diff]),
                use_alias_for    = use_alias,
            ))

    return specs


def coverage_report(specs: Dict[str, List[CaseSpec]]) -> str:
    """Return a human-readable coverage summary."""
    from collections import Counter
    all_contams: List[str] = []
    for cases in specs.values():
        for s in cases:
            all_contams.extend(s.contaminants)

    counter = Counter(all_contams)
    unique_names, _ = data_loader.load_taxonomy()

    missing = [n for n in unique_names if n not in counter]
    lines = [
        f"Total specs generated : {sum(len(v) for v in specs.values())}",
        f"Unique taxonomy names : {len(unique_names)}",
        f"Covered contaminants  : {len(counter)}",
        f"Missing from coverage : {len(missing)}",
    ]
    if missing:
        lines.append(f"  → {missing}")
    lines.append(f"\nPer-difficulty counts :")
    for d, cases in specs.items():
        lines.append(f"  {d:10s}: {len(cases)} new cases")
    return "\n".join(lines)
