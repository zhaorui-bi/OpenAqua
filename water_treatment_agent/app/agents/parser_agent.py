"""
Task Parser Agent
-----------------
Converts raw user input (natural language or structured form) into a
NormalizedQuery validated by Pydantic.

Two modes:
  - NL mode  : raw_query string provided → call LLM → parse JSON
  - Rule mode : structured fields provided → normalize via taxonomy (no LLM)
  - Mixed     : both provided → LLM fills gaps, explicit fields override

Fallback: if OPENROUTER_API_KEY is unset, always uses rule mode.
"""
from __future__ import annotations

import json
import uuid
from typing import Any, Dict, Optional

from openai import OpenAI

from app.agents.prompts import PARSER_SYSTEM_PROMPT
from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.schemas import (
    NormalizedQuery,
    TreatmentTargets,
    UserConstraints,
    UserQuery,
    WaterQuality,
)
from app.core.taxonomy import get_taxonomy

logger = get_logger(__name__)


class TaskParserAgent:
    """
    Converts a UserQuery into a NormalizedQuery.

    Usage::

        agent = TaskParserAgent()
        normalized = agent.run(user_query)
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
                "TaskParserAgent: OPENROUTER_API_KEY not set — running in rule-only mode"
            )


    def run(self, query: UserQuery) -> NormalizedQuery:
        """
        Parse and normalize *query* into a validated NormalizedQuery.

        Raises
        ------
        ValueError  if the resulting query has no recognizable contaminants
                    and no raw_query text to fall back on.
        """
        query_id = query.query_id or str(uuid.uuid4())[:8]
        logger.info("TaskParserAgent: processing query_id=%s", query_id)

        # ── Step 1: LLM extraction (only when raw_query present + key available) ──
        llm_data: Dict[str, Any] = {}
        if query.raw_query and self._llm:
            llm_data = self._call_llm(query.raw_query)
            logger.info("TaskParserAgent: LLM extraction succeeded")

        # ── Step 2: Build merged dict (explicit fields win over LLM) ──
        merged = self._merge(query, llm_data)
        merged["query_id"] = query_id

        # ── Step 3: Taxonomy normalization ──
        raw_contaminants: list[str] = merged.get("contaminants") or []
        normalized_contaminants = self._taxonomy.normalize_contaminants(raw_contaminants)
        unrecognized = [c for c in raw_contaminants if self._taxonomy.normalize_contaminant(c) is None]
        merged["contaminants"] = normalized_contaminants

        # ── Step 4: Missing-field detection ──
        missing: list[str] = []
        if not merged.get("source_water") or merged["source_water"] == "unknown":
            missing.append("source_water")
        wq = merged.get("water_quality") or {}
        if not any(v is not None for v in (wq.values() if isinstance(wq, dict) else [])):
            missing.append("water_quality")
        if not normalized_contaminants:
            missing.append("contaminants")
        merged["missing_fields"] = missing

        # ── Step 5: Accumulate assumptions & notes ──
        assumptions: list[str] = list(llm_data.get("assumptions") or [])
        notes: list[str] = list(llm_data.get("normalization_notes") or [])
        if normalized_contaminants:
            notes.append(f"Mapped contaminants: {raw_contaminants} → {normalized_contaminants}")
        if unrecognized:
            notes.append(f"Unrecognized contaminants (dropped): {unrecognized}")
        if not self._llm and query.raw_query:
            assumptions.append("LLM unavailable; NL query not parsed — structured fields used only")
        merged["assumptions"] = assumptions
        merged["normalization_notes"] = notes

        # ── Step 6: Validate via Pydantic ──
        result = NormalizedQuery(**merged)
        logger.info(
            "TaskParserAgent: done — contaminants=%s missing=%s",
            result.contaminants,
            result.missing_fields,
        )
        return result


    def _call_llm(self, raw_query: str) -> Dict[str, Any]:
        """
        Call OpenRouter LLM to extract structured fields from natural-language query.
        Returns an empty dict on any error (graceful degradation).
        """
        assert self._llm is not None
        try:
            response = self._llm.chat.completions.create(
                model=self._settings.default_model,
                temperature=self._settings.llm_temperature,
                max_tokens=self._settings.llm_max_tokens,
                messages=[
                    {"role": "system", "content": PARSER_SYSTEM_PROMPT},
                    {"role": "user", "content": raw_query},
                ],
            )
            content = response.choices[0].message.content or ""
            # Strip accidental markdown fences
            content = content.strip()
            if content.startswith("```"):
                content = content.split("```")[1]
                if content.startswith("json"):
                    content = content[4:]
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning("TaskParserAgent: LLM returned invalid JSON — %s", e)
        except Exception as e:
            logger.warning("TaskParserAgent: LLM call failed — %s", e)
        return {}


    def _merge(self, query: UserQuery, llm_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merge LLM-extracted data with explicit structured fields.
        Explicit fields always take precedence over LLM output.
        """
        # Start from LLM output as base
        merged: Dict[str, Any] = {
            "source_water": llm_data.get("source_water") or "unknown",
            "water_quality": llm_data.get("water_quality") or {},
            "contaminants": llm_data.get("contaminants") or [],
            "treatment_targets": llm_data.get("treatment_targets") or {},
            "constraints": llm_data.get("constraints") or {},
            "context": llm_data.get("context"),
        }

        # Override with explicit structured fields (non-None wins)
        if query.source_water:
            merged["source_water"] = query.source_water
        if query.water_quality:
            # Merge at sub-field level
            llm_wq = merged.get("water_quality") or {}
            explicit_wq = query.water_quality.model_dump(exclude_none=True, exclude={"extra"})
            llm_wq.update(explicit_wq)
            merged["water_quality"] = llm_wq
        if query.contaminants:
            merged["contaminants"] = query.contaminants
        if query.treatment_targets:
            llm_tt = merged.get("treatment_targets") or {}
            explicit_tt = query.treatment_targets.model_dump(exclude_none=True)
            llm_tt.update(explicit_tt)
            merged["treatment_targets"] = llm_tt
        if query.constraints:
            llm_c = merged.get("constraints") or {}
            explicit_c = query.constraints.model_dump(exclude_none=True, exclude={"extra"})
            llm_c.update(explicit_c)
            merged["constraints"] = llm_c
        if query.context:
            merged["context"] = query.context

        return merged
