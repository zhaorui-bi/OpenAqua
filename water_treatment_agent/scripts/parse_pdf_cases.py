"""
parse_pdf_cases.py — Extract case studies from EPA PDF/HTML files into kb_cases.json
-------------------------------------------------------------------------------------
Reads all PDF and HTML files from:
  data/case-level/epa_cwsrf/
  data/case-level/epa_reuse/

Uses LLM (via OpenRouter) to extract structured case fields from raw text,
then writes the combined results to:
  data/case-level/kb_cases.json

After running this script, rebuild indexes:
  python scripts/build_indexes.py

Dependencies (add to env if missing):
  pip install pdfplumber beautifulsoup4

Usage:
  python scripts/parse_pdf_cases.py
  python scripts/parse_pdf_cases.py --dry-run   # extract text only, skip LLM
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(ROOT))

from app.core.config import get_settings
from app.core.logger import get_logger

log = get_logger("parse_pdf_cases")

CASE_LEVEL_DIR = ROOT / "data" / "case-level"
SOURCE_DIRS = [
    CASE_LEVEL_DIR / "epa_cwsrf",
    CASE_LEVEL_DIR / "epa_reuse",
]
OUTPUT_PATH = CASE_LEVEL_DIR / "kb_cases.json"


_EXTRACT_SYSTEM_PROMPT = """\
You are a water treatment data extraction assistant.
Given the text of a water treatment case study document, extract a structured JSON object.

Return ONLY a JSON object (no markdown, no explanation) with these fields:
{
  "case_id": "auto",
  "title": "short descriptive title (max 80 chars)",
  "source_water": "one of: groundwater, surface water, brackish water, wastewater, stormwater, municipal tap, unknown",
  "water_quality": {
    "pH": null or number,
    "turbidity_NTU": null or number,
    "arsenic_ug_L": null or number,
    "nitrate_mg_L": null or number,
    "fluoride_mg_L": null or number,
    "toc_mg_L": null or number,
    "iron_mg_L": null or number,
    "hardness_mg_L": null or number,
    "e_coli_CFU_100mL": null or number
  },
  "contaminants": ["list of contaminant names found, e.g. Arsenic, Nitrate, PFOA, E. coli"],
  "treatment_chain": ["ordered list of treatment unit names as strings"],
  "key_units": ["1-3 most critical treatment units"],
  "outcome": "1-2 sentences describing treatment performance and compliance achieved",
  "performance": {"removal_pct": null or number, "effluent_value": null, "target_standard": ""},
  "constraints": {
    "budget": null or "low/medium/high",
    "energy": null or "limited/grid_connected",
    "brine_disposal": null or true/false,
    "operator_skill": null or "low/medium/high"
  },
  "region": "geographic region or country mentioned",
  "scale": "village/community/municipal/utility/unknown",
  "references": []
}

Rules:
- If a field cannot be determined from the text, use null or empty list.
- For treatment_chain, use standard process names (e.g. "Coagulation", "Filtration",
  "Granular Activated Carbon", "Ion Exchange", "Membrane Separation", "Chlorine", etc.)
- Do not invent data not present in the text.
- contaminants must be a non-empty list; if unclear write ["unknown"].
"""



def extract_text_pdf(path: Path) -> str:
    """Extract plain text from a PDF using pdfplumber."""
    try:
        import pdfplumber
    except ImportError:
        log.error("pdfplumber not installed. Run: pip install pdfplumber")
        raise

    pages_text: List[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            text = page.extract_text()
            if text:
                pages_text.append(text)
    return "\n".join(pages_text)


def extract_text_html(path: Path) -> str:
    """Extract plain text from an HTML file using BeautifulSoup."""
    try:
        from bs4 import BeautifulSoup
    except ImportError:
        log.error("beautifulsoup4 not installed. Run: pip install beautifulsoup4")
        raise

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        soup = BeautifulSoup(f.read(), "html.parser")
    # Remove script/style noise
    for tag in soup(["script", "style", "nav", "footer", "header"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def extract_text(path: Path) -> Optional[str]:
    """Dispatch to PDF or HTML extractor based on file extension."""
    suffix = path.suffix.lower()
    try:
        if suffix == ".pdf":
            text = extract_text_pdf(path)
        elif suffix in (".html", ".htm"):
            text = extract_text_html(path)
        else:
            log.warning("Unsupported file type: %s — skipping", path.name)
            return None
        if not text or len(text.strip()) < 100:
            log.warning("Too little text extracted from %s — skipping", path.name)
            return None
        log.info("Extracted %d chars from %s", len(text), path.name)
        return text
    except Exception as exc:
        log.warning("Failed to extract text from %s: %s", path.name, exc)
        return None



def llm_extract(text: str, filename: str, client: Any, model: str) -> Optional[Dict]:
    """Call LLM to extract structured case data from raw text."""
    # Truncate to avoid token limits: first 6000 chars usually covers the key content
    truncated = text[:6000]
    if len(text) > 6000:
        # Also grab last 1000 chars (may contain outcomes/conclusions)
        truncated += "\n...\n" + text[-1000:]

    user_msg = (
        f"Document filename: {filename}\n\n"
        f"Document text:\n{truncated}"
    )

    try:
        response = client.chat.completions.create(
            model=model,
            temperature=0.1,
            max_tokens=1200,
            messages=[
                {"role": "system", "content": _EXTRACT_SYSTEM_PROMPT},
                {"role": "user", "content": user_msg},
            ],
        )
        raw = (response.choices[0].message.content or "").strip()

        # Strip markdown code fences if present
        if raw.startswith("```"):
            raw = re.sub(r"^```[a-z]*\n?", "", raw)
            raw = re.sub(r"\n?```$", "", raw)

        data = json.loads(raw)
        return data
    except json.JSONDecodeError as exc:
        log.warning("LLM returned invalid JSON for %s: %s", filename, exc)
        return None
    except Exception as exc:
        log.warning("LLM call failed for %s: %s", filename, exc)
        return None


def collect_files() -> List[Path]:
    """Collect all PDF and HTML files from source directories."""
    files: List[Path] = []
    for d in SOURCE_DIRS:
        if not d.exists():
            log.warning("Source directory not found: %s", d)
            continue
        for ext in ("*.pdf", "*.html", "*.htm"):
            files.extend(sorted(d.glob(ext)))
    log.info("Found %d files to process", len(files))
    return files


def assign_case_ids(cases: List[Dict], start: int = 1) -> List[Dict]:
    """Replace 'auto' case_id with sequential CASE-NNN."""
    for i, case in enumerate(cases, start=start):
        if not case.get("case_id") or case["case_id"] == "auto":
            case["case_id"] = f"CASE-{i:03d}"
    return cases


def main(dry_run: bool = False) -> None:
    settings = get_settings()

    if not dry_run and not settings.openrouter_api_key:
        log.error(
            "OPENROUTER_API_KEY not set in .env — "
            "cannot run LLM extraction. Use --dry-run to test text extraction only."
        )
        sys.exit(1)

    files = collect_files()
    if not files:
        log.error("No files found in source directories. Exiting.")
        sys.exit(1)

    client = None
    model = settings.default_model
    if not dry_run:
        from openai import OpenAI
        client = OpenAI(
            api_key=settings.openrouter_api_key,
            base_url=settings.openrouter_base_url,
        )
        log.info("LLM client initialised — model: %s", model)

    cases: List[Dict] = []
    skipped = 0

    for i, path in enumerate(files, 1):
        log.info("[%d/%d] Processing: %s", i, len(files), path.name)
        print(f"  [{i}/{len(files)}] {path.name}", end=" ... ", flush=True)

        # Step 1: extract raw text
        text = extract_text(path)
        if text is None:
            print("SKIP (text extraction failed)")
            skipped += 1
            continue

        if dry_run:
            print(f"OK ({len(text)} chars) [dry-run]")
            continue

        # Step 2: LLM structured extraction
        case_data = llm_extract(text, path.name, client, model)
        if case_data is None:
            print("SKIP (LLM extraction failed)")
            skipped += 1
            continue

        # Step 3: add provenance metadata
        case_data["_source_file"] = path.name
        case_data["_source_dir"] = path.parent.name
        cases.append(case_data)
        print(f"OK — '{case_data.get('title', '?')[:60]}'")

        # Polite rate-limit pause between LLM calls
        time.sleep(0.5)

    if dry_run:
        print(f"\nDry-run complete. {len(files)} files found, {skipped} would be skipped.")
        return

    if not cases:
        log.error("No cases extracted. Check LLM logs above.")
        sys.exit(1)

    # Assign sequential IDs
    cases = assign_case_ids(cases)

    output = {
        "version": "1.0",
        "description": (
            "KB_case: water treatment case studies extracted from EPA CWSRF and "
            "Water Reuse program documents"
        ),
        "cases": cases,
    }

    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        json.dump(output, f, ensure_ascii=False, indent=2)

    print(f"\n✓ Wrote {len(cases)} cases → {OUTPUT_PATH.relative_to(ROOT)}")
    print(f"  Skipped: {skipped} files")
    print(f"\nNext step — rebuild indexes:")
    print(f"  python scripts/build_indexes.py")
    log.info("parse_pdf_cases done: %d cases written, %d skipped", len(cases), skipped)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Extract water treatment cases from EPA PDFs/HTMLs")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Extract text only, skip LLM calls (useful for testing extraction)",
    )
    args = parser.parse_args()
    main(dry_run=args.dry_run)
