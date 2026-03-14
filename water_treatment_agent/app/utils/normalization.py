"""
Normalization utilities: unit conversion, string cleaning, synonym mapping.
"""
from __future__ import annotations

import re
from typing import Optional



_UG_L_PATTERN = re.compile(r"(\d+\.?\d*)\s*(ug/l|μg/l|µg/l|ug/L|µg/L|μg/L)", re.IGNORECASE)
_MG_L_PATTERN = re.compile(r"(\d+\.?\d*)\s*(mg/l|mg/L)", re.IGNORECASE)


def extract_concentration_ug_L(text: str) -> Optional[float]:
    """Parse a concentration value from text, returning µg/L."""
    m = _UG_L_PATTERN.search(text)
    if m:
        return float(m.group(1))
    m = _MG_L_PATTERN.search(text)
    if m:
        return float(m.group(1)) * 1000  # mg/L → µg/L
    return None


def normalize_string(s: str) -> str:
    """Lowercase, strip, collapse whitespace."""
    return re.sub(r"\s+", " ", s.strip().lower())
