"""
Taxonomy loader: loads and queries the real taxonomy.json for contaminant
normalization, and dynamically scans treatment unit names from the tdb
directory structure.

Real taxonomy.json format (flat rows, one synonym per row):
    [{"Contaminant Name": "Arsenic", "Synonyms": "As"}, ...]

Treatment units are derived from treatment file names in unit-level/tdb/:
    treatment_{ContaminantName}_{Function}.json  →  "Function With Spaces"
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Dict, List, Optional, Set

from app.core.config import get_settings


class TaxonomyManager:
    """
    Loads the real taxonomy.json and provides lookup helpers.

    Contaminant canonical IDs are the exact "Contaminant Name" values from
    the database (e.g. "Arsenic", "1,4-dioxane", "PFOA").

    Treatment units are scanned from treatment file names under unit_kb_dir,
    normalized to space-separated form (e.g. "Granular Activated Carbon").
    """

    def __init__(
        self,
        taxonomy_path: Optional[Path] = None,
        unit_kb_dir: Optional[Path] = None,
    ) -> None:
        cfg = get_settings()
        taxonomy_path = taxonomy_path or cfg.taxonomy_path
        unit_kb_dir = unit_kb_dir or cfg.unit_kb_dir

        with open(taxonomy_path, "r", encoding="utf-8") as f:
            raw = json.load(f)

        self._id_to_contaminant: Dict[str, dict] = {}
        self._synonym_map: Dict[str, str] = {}

        # Real format: flat list of {"Contaminant Name": ..., "Synonyms": ...}
        # Group rows by canonical name, collect synonyms
        groups: Dict[str, List[str]] = defaultdict(list)
        for row in raw:
            name = row.get("Contaminant Name", "").strip()
            synonym = row.get("Synonyms", "").strip()
            if name:
                if synonym:
                    groups[name].append(synonym)
                else:
                    groups.setdefault(name, [])

        for canonical_name, synonyms in groups.items():
            cid = canonical_name
            self._id_to_contaminant[cid] = {
                "id": cid,
                "name": canonical_name,
                "synonyms": synonyms,
            }
            self._synonym_map[cid.lower()] = cid
            for syn in synonyms:
                if syn:
                    self._synonym_map[syn.lower()] = cid

        # Scan treatment units from directory file names (no per-file I/O)
        self._valid_units: Set[str] = self._scan_treatment_units(unit_kb_dir)


    def normalize_contaminant(self, name: str) -> Optional[str]:
        """Return canonical contaminant ID, or None if not found."""
        return self._synonym_map.get(name.strip().lower())

    def normalize_contaminants(self, names: List[str]) -> List[str]:
        """Normalize a list; unrecognized names are dropped (logged separately)."""
        result = []
        for n in names:
            cid = self.normalize_contaminant(n)
            if cid:
                result.append(cid)
        return list(dict.fromkeys(result))  # preserve order, deduplicate

    def get_contaminant(self, cid: str) -> Optional[dict]:
        return self._id_to_contaminant.get(cid)

    def all_contaminant_ids(self) -> List[str]:
        return list(self._id_to_contaminant.keys())


    def is_valid_unit(self, unit: str) -> bool:
        """Return True if unit is in the controlled process taxonomy.

        Comparison is case-insensitive; both underscore and space variants match.
        """
        normalized = unit.strip().replace("_", " ").lower()
        return normalized in {u.lower() for u in self._valid_units}

    def validate_chain(self, chain: List[str]) -> List[str]:
        """Return list of invalid unit names in chain."""
        return [u for u in chain if not self.is_valid_unit(u)]

    def all_treatment_units(self) -> List[str]:
        return sorted(self._valid_units)


    @staticmethod
    def _scan_treatment_units(unit_kb_dir: Optional[Path]) -> Set[str]:
        """
        Derive valid treatment unit names by inspecting treatment file names.

        File naming convention:
            tdb/{ContaminantName}/tdb_{ContaminantName}_treatment/
                treatment_{ContaminantName}_{FunctionWithUnderscores}.json

        ContaminantNames never contain underscores (they use commas, hyphens,
        spaces), so stripping the known prefix leaves exactly the function name.
        """
        units: Set[str] = set()
        if not unit_kb_dir or not unit_kb_dir.exists():
            return units

        for contaminant_dir in unit_kb_dir.iterdir():
            if not contaminant_dir.is_dir():
                continue
            contaminant_name = contaminant_dir.name
            treatment_dir = contaminant_dir / f"tdb_{contaminant_name}_treatment"
            if not treatment_dir.exists():
                continue

            prefix = f"treatment_{contaminant_name}_"
            for json_file in treatment_dir.glob("treatment_*.json"):
                stem = json_file.stem  # e.g. "treatment_Arsenic_Granular_Activated_Carbon"
                if not stem.startswith(prefix):
                    continue
                func_underscored = stem[len(prefix):]
                if func_underscored.lower() == "overall":
                    continue
                # Convert underscore-separated to space-separated canonical form
                func = func_underscored.replace("_", " ")
                units.add(func)

        return units


# Module-level singleton (lazy)
_manager: Optional[TaxonomyManager] = None


def get_taxonomy() -> TaxonomyManager:
    """Return the module-level TaxonomyManager singleton."""
    global _manager
    if _manager is None:
        _manager = TaxonomyManager()
    return _manager
