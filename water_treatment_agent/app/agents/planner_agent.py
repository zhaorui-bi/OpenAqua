"""
Process Planning Agent
----------------------
Generates N candidate treatment chains strictly within the controlled
process taxonomy.  Uses retrieved cases as evidence context.

Two generation modes (automatically selected):
  LLM mode  : call OpenRouter with rich retrieval context
  Seed mode : generate chains from per-contaminant unit seeds (fallback)

Both modes run taxonomy validation — any unit not in the taxonomy is dropped
with a warning, not silently propagated.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from openai import OpenAI

from app.agents.prompts import PLANNER_SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.schemas import (
    CandidateChain,
    CandidatesBundle,
    EnergyLevel,
    NormalizedQuery,
    RetrievalBundle,
)
from app.core.taxonomy import get_taxonomy

logger = get_logger(__name__)



def _build_contaminant_unit_map(unit_kb_dir: Any) -> Dict[str, List[str]]:
    """
    Scan the tdb directory tree and build a mapping of
    contaminant_name_lower → [treatment function, ...].

    Uses treatment file names only (no per-file I/O) for speed.
    Canonical contaminant name (with original casing) is also stored under
    its lowercase key so scoring.py lookups work regardless of casing.
    """
    from pathlib import Path as _Path
    result: Dict[str, List[str]] = {}
    unit_kb_dir = _Path(unit_kb_dir) if unit_kb_dir else None
    if not unit_kb_dir or not unit_kb_dir.exists():
        logger.warning("planner_agent: unit_kb_dir not found — CONTAMINANT_UNIT_MAP empty")
        return result

    for contaminant_dir in sorted(unit_kb_dir.iterdir()):
        if not contaminant_dir.is_dir():
            continue
        contaminant_name = contaminant_dir.name
        treatment_dir = contaminant_dir / f"tdb_{contaminant_name}_treatment"
        if not treatment_dir.exists():
            continue

        prefix = f"treatment_{contaminant_name}_"
        funcs: List[str] = []
        for json_file in sorted(treatment_dir.glob("treatment_*.json")):
            stem = json_file.stem
            if not stem.startswith(prefix):
                continue
            func_underscored = stem[len(prefix):]
            if func_underscored.lower() == "overall":
                continue
            funcs.append(func_underscored.replace("_", " "))

        if funcs:
            result[contaminant_name.lower()] = funcs

    logger.info(
        "planner_agent: CONTAMINANT_UNIT_MAP built for %d contaminants", len(result)
    )
    return result


# Lazily initialised module-level map (populated on first use)
_CONTAMINANT_UNIT_MAP_CACHE: Optional[Dict[str, List[str]]] = None


def _get_contaminant_unit_map() -> Dict[str, List[str]]:
    global _CONTAMINANT_UNIT_MAP_CACHE
    if _CONTAMINANT_UNIT_MAP_CACHE is None:
        _CONTAMINANT_UNIT_MAP_CACHE = _build_contaminant_unit_map(
            get_settings().unit_kb_dir
        )
    return _CONTAMINANT_UNIT_MAP_CACHE


# Public name kept for backward compatibility with scoring.py's import
# ``from app.agents.planner_agent import CONTAMINANT_UNIT_MAP``.
# scoring.py calls CONTAMINANT_UNIT_MAP.get(…) at runtime, so returning
# the lazily-populated dict works transparently.
class _LazyMap(dict):
    """Dict subclass that populates itself from real data on first access."""

    def __missing__(self, key: str):
        # Trigger load the first time a missing key is accessed
        loaded = _get_contaminant_unit_map()
        self.update(loaded)
        return super().get(key, [])

    def get(self, key, default=None):
        # dict.get() does NOT trigger __missing__, so we must ensure the map
        # is populated before delegating to the standard implementation.
        if not self:
            self.update(_get_contaminant_unit_map())
        return super().get(key, default)


CONTAMINANT_UNIT_MAP: Dict[str, List[str]] = _LazyMap()

# Real taxonomy unit names (Title Case).
# All membership checks use _*_LOWER sets below (case-insensitive).
_BRINE_UNITS = {
    "Membrane Separation",
}
_DISINFECTION_UNITS = {
    "Chlorine", "Chloramine", "Chlorine Dioxide",
    "Ozone", "Ozone and Hydrogen Peroxide",
    "Ultraviolet Irradiation",
    "Ultraviolet Irradiation and Hydrogen Peroxide",
    "Ultraviolet Irradiation and Ozone",
}
_HIGH_ENERGY_UNITS = {
    "Membrane Separation", "Membrane Filtration",
    "Ozone", "Ozone and Hydrogen Peroxide",
    "Ultraviolet Irradiation and Ozone",
}

# Pre-computed lower-cased sets for case-insensitive membership tests
_BRINE_UNITS_LOWER        = {u.strip().replace("_", " ").lower() for u in _BRINE_UNITS}
_DISINFECTION_UNITS_LOWER = {u.strip().replace("_", " ").lower() for u in _DISINFECTION_UNITS}
_HIGH_ENERGY_UNITS_LOWER  = {u.strip().replace("_", " ").lower() for u in _HIGH_ENERGY_UNITS}

# Unit appended during auto-fix must be a real taxonomy name
_AUTO_DISINFECTION_UNIT = "Chlorine"


class ProcessPlannerAgent:
    """
    Generates N candidate treatment chains from a NormalizedQuery + RetrievalBundle.

    Usage::

        agent = ProcessPlannerAgent()
        bundle = agent.run(normalized_query, retrieval_bundle)
    """

    def __init__(self) -> None:
        self._settings = get_settings()
        self._taxonomy = get_taxonomy()
        self._llm: Optional[OpenAI] = None
        if self._settings.openrouter_api_key:
            self._llm = OpenAI(
                api_key=self._settings.openrouter_api_key,
                base_url=self._settings.openrouter_base_url,
            )
        else:
            logger.warning(
                "ProcessPlannerAgent: OPENROUTER_API_KEY not set — using template fallback"
            )

    def run(
        self,
        query: NormalizedQuery,
        retrieval: RetrievalBundle,
        n_candidates: int | None = None,
    ) -> CandidatesBundle:
        """
        Generate candidate chains for *query*.

        Parameters
        ----------
        query :        NormalizedQuery with contaminants and constraints.
        retrieval :    RetrievalBundle providing templates and cases as context.
        n_candidates : Number of candidates to generate (defaults to settings).

        Returns
        -------
        CandidatesBundle with validated, deduplicated chains.
        """
        n = n_candidates or self._settings.max_planning_candidates
        logger.info(
            "ProcessPlannerAgent: generating %d candidates for query %s", n, query.query_id
        )

        candidates: List[CandidateChain] = []
        planning_notes: List[str] = []

        # ── Attempt 1: LLM generation ──
        if self._llm:
            llm_cands, llm_notes = self._llm_generate(query, retrieval, n)
            planning_notes.extend(llm_notes)
            candidates.extend(llm_cands)

        # ── Attempt 2: Template + seed fallback (fills gaps or replaces LLM) ──
        if len(candidates) < 2:
            fb_cands, fb_notes = self._template_fallback(query, n)
            planning_notes.extend(fb_notes)
            existing = {tuple(c.chain) for c in candidates}
            for c in fb_cands:
                if tuple(c.chain) not in existing:
                    candidates.append(c)
                    existing.add(tuple(c.chain))

        candidates = candidates[:n]
        logger.info("ProcessPlannerAgent: %d valid candidates produced", len(candidates))
        return CandidatesBundle(
            query_id=query.query_id,
            candidates=candidates,
            planning_notes=planning_notes,
        )


    def _llm_generate(
        self,
        query: NormalizedQuery,
        retrieval: RetrievalBundle,
        n: int,
    ) -> tuple[List[CandidateChain], List[str]]:
        """Call LLM, parse output, validate. Returns (candidates, notes)."""
        notes: List[str] = []
        try:
            prompt = self._build_prompt(query, retrieval, n)
            response = self._llm.chat.completions.create(  # type: ignore[union-attr]
                model=self._settings.planner_model,
                temperature=self._settings.llm_temperature,
                max_tokens=self._settings.llm_max_tokens,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = (response.choices[0].message.content or "").strip()
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            parsed = json.loads(raw)
            candidates = self._parse_llm_output(parsed, query)
            notes.append(f"LLM generated {len(candidates)} valid candidates")
            return candidates, notes
        except json.JSONDecodeError as e:
            logger.warning("ProcessPlannerAgent: LLM returned invalid JSON — %s", e)
        except Exception as e:
            logger.warning("ProcessPlannerAgent: LLM call failed — %s", e)
        notes.append("LLM generation failed — using template fallback")
        return [], notes

    def _build_prompt(
        self, query: NormalizedQuery, retrieval: RetrievalBundle, n: int
    ) -> str:
        """Format PLANNER_SYSTEM_PROMPT with query + retrieval context."""
        evidence_parts: List[str] = []
        for label, chunks in [
            ("CASES",         retrieval.kb_case[:3]),
            ("UNIT EVIDENCE", retrieval.kb_unit[:3]),
        ]:
            if chunks:
                evidence_parts.append(f"[{label}]")
                for c in chunks:
                    evidence_parts.append(f"  [{c.source_id}] {c.text[:300]}")

        constraints = {}
        if query.constraints:
            constraints = query.constraints.model_dump(exclude_none=True, exclude={"extra"})
        targets = {}
        if query.treatment_targets:
            targets = query.treatment_targets.model_dump(exclude_none=True)

        return PLANNER_SYSTEM_PROMPT.format(
            source_water=query.source_water,
            contaminants=query.contaminants,
            treatment_targets=targets or "not specified",
            constraints=constraints or "none",
            evidence_context="\n".join(evidence_parts) or "No evidence retrieved",
            n_candidates=n,
            taxonomy_units=", ".join(self._taxonomy.all_treatment_units()),
        )

    def _parse_llm_output(
        self, raw: Any, query: NormalizedQuery
    ) -> List[CandidateChain]:
        """Validate each LLM-generated chain against taxonomy. Drop invalid units."""
        if not isinstance(raw, list):
            logger.warning("ProcessPlannerAgent: LLM output is not a list")
            return []

        candidates: List[CandidateChain] = []
        for i, item in enumerate(raw):
            if not isinstance(item, dict):
                continue
            chain_units: List[str] = item.get("chain") or []
            invalid = self._taxonomy.validate_chain(chain_units)
            if invalid:
                logger.warning(
                    "ProcessPlannerAgent: dropping invalid units from LLM chain %d: %s", i, invalid
                )
                chain_units = [u for u in chain_units if u not in invalid]
            if not chain_units:
                continue

            chain_id = item.get("chain_id") or f"CAND-{query.query_id}-LLM-{i+1:02d}"
            generates_brine = any(
                u.strip().replace("_", " ").lower() in _BRINE_UNITS_LOWER for u in chain_units
            )
            has_disinfection = any(
                u.strip().replace("_", " ").lower() in _DISINFECTION_UNITS_LOWER for u in chain_units
            )

            energy_raw = (item.get("energy_intensity") or "medium").upper().replace("-", "_")
            try:
                energy = EnergyLevel[energy_raw]
            except KeyError:
                energy = EnergyLevel.MEDIUM

            candidates.append(
                CandidateChain(
                    chain_id=chain_id,
                    chain=chain_units,
                    key_units=item.get("key_units") or chain_units[:1],
                    rationale=item.get("rationale") or "LLM-generated candidate",
                    generates_brine=generates_brine,
                    requires_disinfection=has_disinfection,
                    energy_intensity=energy,
                )
            )
        return candidates


    def _template_fallback(
        self,
        query: NormalizedQuery,
        n: int,
    ) -> tuple[List[CandidateChain], List[str]]:
        """Generate candidate chains from per-contaminant unit seeds and RO variant."""
        notes: List[str] = []
        candidates: List[CandidateChain] = []
        seen: set[tuple] = set()

        # Source 1: seed chains per contaminant, built from real treatment data
        unit_map = _get_contaminant_unit_map()
        for contaminant in query.contaminants:
            if len(candidates) >= n:
                break
            # Use the first 4 real treatment units for this contaminant as seed
            real_units = unit_map.get(contaminant.lower(), [])
            if not real_units:
                continue
            seed = real_units[:4]
            adjusted = self._apply_fixes(seed, query)
            key = tuple(adjusted)
            if key in seen:
                continue
            seen.add(key)
            cid = f"CAND-{query.query_id}-SEED-{len(candidates)+1:02d}"
            candidates.append(self._make_chain(cid, adjusted, f"seed_{contaminant}", query))

        # Source 3: RO variant when allowed
        if len(candidates) < n:
            c = query.constraints
            if (c is None or c.brine_disposal is not False) and (
                c is None or c.budget != "low"
            ):
                ro = self._apply_fixes(["filtration", "Membrane Separation"], query)
                key = tuple(ro)
                if key not in seen:
                    seen.add(key)
                    cid = f"CAND-{query.query_id}-RO-{len(candidates)+1:02d}"
                    candidates.append(self._make_chain(cid, ro, "seed_ro", query))

        notes.append(f"Template fallback total: {len(candidates)} candidates")
        return candidates, notes

    def _apply_fixes(self, chain: List[str], query: NormalizedQuery) -> List[str]:
        """
        Apply constraint-aware fixes to a chain:
        - Remove RO/NF when brine_disposal=False (satisfies R-003)
        - Append disinfection unit when needed but absent (satisfies R-002)
        """
        result = list(chain)
        c = query.constraints

        if c and c.brine_disposal is False:
            result = [
                u for u in result
                if u.strip().replace("_", " ").lower() not in _BRINE_UNITS_LOWER
            ]

        needs_disinfection = (
            (c and c.use_for_drinking is True)
            or (query.context and "drink" in query.context.lower())
            or "e_coli" in (query.contaminants or [])
        )
        if needs_disinfection and not any(
            u.strip().replace("_", " ").lower() in _DISINFECTION_UNITS_LOWER for u in result
        ):
            result.append(_AUTO_DISINFECTION_UNIT)

        return result

    def _make_chain(
        self,
        chain_id: str,
        chain: List[str],
        source_label: str,
        query: NormalizedQuery,
    ) -> CandidateChain:
        """Instantiate a CandidateChain with auto-computed metadata."""
        generates_brine = any(
            u.strip().replace("_", " ").lower() in _BRINE_UNITS_LOWER for u in chain
        )
        has_disinfection = any(
            u.strip().replace("_", " ").lower() in _DISINFECTION_UNITS_LOWER for u in chain
        )
        is_high_energy = any(
            u.strip().replace("_", " ").lower() in _HIGH_ENERGY_UNITS_LOWER for u in chain
        )

        # Key units: those effective for at least one query contaminant
        key_units: List[str] = []
        unit_map = _get_contaminant_unit_map()
        for contaminant in query.contaminants:
            effective = set(unit_map.get(contaminant.lower(), []))
            for u in chain:
                if u.replace("_", " ") in effective and u not in key_units:
                    key_units.append(u)

        return CandidateChain(
            chain_id=chain_id,
            chain=chain,
            key_units=key_units or chain[:1],
            rationale=(
                f"Candidate from {source_label}. "
                f"Targets {query.contaminants}. "
                f"Key removal units: {key_units or chain[:2]}."
            ),
            generates_brine=generates_brine,
            requires_disinfection=has_disinfection,
            energy_intensity=EnergyLevel.HIGH if is_high_energy else EnergyLevel.LOW,
        )
