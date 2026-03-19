"""
Index Builder
-------------
Reads the real unit-level tdb/ directory, chunks documents by role, builds
a BM25Okapi index, and persists the corpus + index to data/processed/indexes/.

Chunk strategy
--------------
tdb/{Name}/tdb_{Name}_description.json  → one chunk per file  (kb_unit, subtype=description)
tdb/{Name}/tdb_{Name}_info.json         → one chunk per file  (kb_unit, subtype=info)
tdb/{Name}/ref/*.json                   → one chunk per file  (kb_unit, subtype=ref)
tdb/{Name}/fatetrans/*.json             → one chunk per file  (kb_unit, subtype=fatetrans)
tdb/{Name}/properties/*.json            → one chunk per file  (kb_unit, subtype=properties)
tdb/{Name}/tdb_{Name}_treatment/treatment_{Name}_{Func}.json
                                        → one chunk per file  (kb_unit, subtype=treatment)
                                          source_id = "treatment_{Name}_{Func}"
data/case-level/kb_cases.json           → one chunk per case  (kb_case)   [optional]

Run via:
    python scripts/build_indexes.py
"""
from __future__ import annotations

import json
import pickle
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.config import get_settings
from app.core.logger import get_logger

logger = get_logger(__name__)


def _flatten_to_text(obj: Any, depth: int = 0) -> str:
    """Recursively flatten a JSON object to a readable text string."""
    if isinstance(obj, dict):
        parts = []
        for k, v in obj.items():
            parts.append(f"{k}: {_flatten_to_text(v, depth + 1)}")
        return " | ".join(parts)
    if isinstance(obj, list):
        return " ".join(_flatten_to_text(i, depth + 1) for i in obj)
    if obj is None:
        return ""
    return str(obj)


def _tokenize(text: str) -> List[str]:
    """Simple whitespace + punctuation tokenizer, lowercase."""
    return re.findall(r"[a-zA-Z0-9\u4e00-\u9fff]+", text.lower())


class IndexBuilder:
    """Builds and persists retrieval indexes from the real unit-level tdb/ tree."""

    def __init__(self) -> None:
        self._settings = get_settings()


    def build_all(self) -> int:
        """
        Build all indexes from unit_kb_dir and optional case/template JSONs.

        Returns
        -------
        int  Number of chunks indexed.
        """
        logger.info("IndexBuilder: scanning unit_kb_dir=%s", self._settings.unit_kb_dir)
        corpus = self._build_corpus()
        logger.info("IndexBuilder: %d chunks built", len(corpus))

        index_dir: Path = self._settings.index_dir
        index_dir.mkdir(parents=True, exist_ok=True)

        self._save_corpus(corpus, index_dir)
        self._build_bm25(corpus, index_dir)

        logger.info("IndexBuilder: indexes written to %s", index_dir)
        return len(corpus)


    def _build_corpus(self) -> List[Dict[str, Any]]:
        """
        Walk unit_kb_dir contaminant directories and produce a flat list of
        chunk dicts.  Optionally includes kb_cases.json if it exists.
        """
        corpus: List[Dict[str, Any]] = []

        # 1. Unit-level: iterate over every contaminant directory
        unit_kb_dir = self._settings.unit_kb_dir
        if unit_kb_dir and unit_kb_dir.exists():
            contaminant_dirs = sorted(
                d for d in unit_kb_dir.iterdir() if d.is_dir()
            )
            logger.info("IndexBuilder: found %d contaminant directories", len(contaminant_dirs))
            for contaminant_dir in contaminant_dirs:
                try:
                    chunks = self._chunk_contaminant_dir(contaminant_dir)
                    corpus.extend(chunks)
                except Exception as e:
                    logger.warning(
                        "IndexBuilder: skipping %s — %s", contaminant_dir.name, e
                    )
        else:
            logger.warning("IndexBuilder: unit_kb_dir not found: %s", unit_kb_dir)

        # 2. Optional structured case KB
        cases_path: Optional[Path] = self._settings.case_kb_json
        if cases_path and cases_path.exists():
            try:
                with open(cases_path, encoding="utf-8") as f:
                    data = json.load(f)
                corpus.extend(self._chunk_cases(data))
                logger.info("IndexBuilder: loaded kb_cases.json")
            except Exception as e:
                logger.warning("IndexBuilder: skipping kb_cases.json — %s", e)

        return corpus


    def _chunk_contaminant_dir(self, contaminant_dir: Path) -> List[Dict[str, Any]]:
        """Produce all chunks for one contaminant directory."""
        chunks: List[Dict[str, Any]] = []
        name = contaminant_dir.name

        # Description file
        desc = contaminant_dir / f"tdb_{name}_description.json"
        if desc.exists():
            chunks.extend(self._chunk_tdb_file(desc, name, "description"))

        # Info file
        info = contaminant_dir / f"tdb_{name}_info.json"
        if info.exists():
            chunks.extend(self._chunk_tdb_file(info, name, "info"))

        # Ref files
        ref_dir = contaminant_dir / "ref"
        if ref_dir.exists():
            for f in sorted(ref_dir.glob("*.json")):
                chunks.extend(self._chunk_tdb_file(f, name, "ref"))

        # Fate & transport files
        fatetrans_dir = contaminant_dir / "fatetrans"
        if fatetrans_dir.exists():
            for f in sorted(fatetrans_dir.glob("*.json")):
                chunks.extend(self._chunk_tdb_file(f, name, "fatetrans"))

        # Properties files
        props_dir = contaminant_dir / "properties"
        if props_dir.exists():
            for f in sorted(props_dir.glob("*.json")):
                chunks.extend(self._chunk_tdb_file(f, name, "properties"))

        # Treatment files
        treatment_dir = contaminant_dir / f"tdb_{name}_treatment"
        if treatment_dir.exists():
            for f in sorted(treatment_dir.glob("treatment_*.json")):
                chunks.extend(self._chunk_treatment_file(f, name))

        return chunks

    def _chunk_tdb_file(
        self, path: Path, contaminant: str, subtype: str
    ) -> List[Dict[str, Any]]:
        """Create one chunk for a tdb support file (info/description/ref/etc.)."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("IndexBuilder: skipping %s — %s", path, e)
            return []

        text = _flatten_to_text(data)
        source_id = f"tdb_{contaminant}_{subtype}"
        return [{
            "chunk_id": f"{source_id}::{path.stem}",
            "source_id": source_id,
            "kb_type": "kb_unit",
            "coverage_tags": [contaminant],
            "text": text,
            "tokens": _tokenize(text),
            "metadata": {
                "file": path.name,
                "contaminant": contaminant,
                "subtype": subtype,
            },
        }]

    def _chunk_treatment_file(
        self, path: Path, contaminant: str
    ) -> List[Dict[str, Any]]:
        """
        Create one chunk for a treatment function file.

        source_id follows the convention treatment_{ContaminantName}_{Function}
        so evidence_binding.py can detect it with startswith("treatment_").
        """
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            logger.warning("IndexBuilder: skipping %s — %s", path, e)
            return []

        # Read the Function field directly from the file for accuracy
        func: str = "overall"
        if isinstance(data, dict):
            func = data.get("Function", "overall").strip() or "overall"

        text = _flatten_to_text(data)
        func_slug = func.replace(" ", "_")
        source_id = f"treatment_{contaminant}_{func_slug}"
        chunk_id = f"{source_id}::{path.stem}"

        return [{
            "chunk_id": chunk_id,
            "source_id": source_id,
            "kb_type": "kb_unit",
            "coverage_tags": [contaminant],
            "text": text,
            "tokens": _tokenize(text),
            "metadata": {
                "file": path.name,
                "contaminant": contaminant,
                "function": func,
            },
        }]


    def _chunk_cases(self, data: dict) -> List[Dict[str, Any]]:
        chunks = []
        for case in data.get("cases", []):
            cid = case.get("case_id", "unknown")
            text = _flatten_to_text(case)
            chunks.append({
                "chunk_id": f"kb_cases::{cid}",
                "source_id": "kb_cases",
                "kb_type": "kb_case",
                "coverage_tags": case.get("contaminants", []),
                "text": text,
                "tokens": _tokenize(text),
                "metadata": {
                    "case_id": cid,
                    "title": case.get("title", ""),
                    "chain": case.get("treatment_chain", []),
                },
            })
        return chunks


    def _save_corpus(self, corpus: List[Dict[str, Any]], index_dir: Path) -> None:
        """Write corpus as JSONL (tokens field excluded to keep file lean)."""
        out = index_dir / "corpus.jsonl"
        with open(out, "w", encoding="utf-8") as f:
            for chunk in corpus:
                row = {k: v for k, v in chunk.items() if k != "tokens"}
                f.write(json.dumps(row, ensure_ascii=False) + "\n")
        logger.info("IndexBuilder: corpus saved → %s (%d lines)", out, len(corpus))

    def _build_bm25(self, corpus: List[Dict[str, Any]], index_dir: Path) -> None:
        """Build BM25Okapi index over token lists and pickle it."""
        try:
            from rank_bm25 import BM25Okapi
        except ImportError:
            logger.error("rank-bm25 not installed — run: pip install rank-bm25")
            raise

        token_lists = [chunk["tokens"] for chunk in corpus]
        bm25 = BM25Okapi(token_lists)

        out = index_dir / "bm25_index.pkl"
        with open(out, "wb") as f:
            pickle.dump(bm25, f)
        logger.info("IndexBuilder: BM25 index saved → %s", out)
