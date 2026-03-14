"""Page 3 — Knowledge base ingestion."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

import api_client
from components import sidebar_config

st.set_page_config(page_title="Knowledge Base Ingestion", page_icon="📥", layout="centered")

base_url = sidebar_config()

st.title("📥 Knowledge Base Ingestion")
st.caption("Add new entries to the knowledge base, and the system will asynchronously rebuild the index.")

_KB_TYPES = ["kb_unit", "kb_case"]

_EXAMPLES: dict[str, str] = {
    "kb_unit": json.dumps({
        "unit": "Granular Activated Carbon",
        "contaminants": ["TOC", "PFOA", "Taste & Odor"],
        "notes": "Effective for organic micropollutants and taste/odor control.",
    }, ensure_ascii=False, indent=2),

    "kb_case": json.dumps({
        "case_id": "CASE-NEW",
        "title": "Fluoride Removal by Bone Char Media, Ethiopia",
        "source_water": "groundwater",
        "water_quality": {"fluoride_mg_L": 8.0, "pH": 7.4},
        "contaminants": ["Fluoride"],
        "treatment_chain": ["Adsorptive Media", "Slow Sand Filtration"],
        "outcome": "Fluoride reduced from 8.0 mg/L to 1.4 mg/L using bone char media",
        "constraints": {"budget": "low", "energy": "limited", "brine_disposal": False},
    }, ensure_ascii=False, indent=2),
}

kb_type = st.selectbox("Knowledge Base Type", _KB_TYPES)

# Load-example button updates the textarea key via session_state
if st.button("Load Example"):
    st.session_state["ingest_json"] = _EXAMPLES[kb_type]

json_text = st.text_area(
    "Entry Data (JSON Format)",
    value=st.session_state.get("ingest_json", _EXAMPLES[kb_type]),
    height=220,
    key="ingest_json_area",
)

if st.button("Submit", type="primary"):
    try:
        data = json.loads(json_text)
    except json.JSONDecodeError as exc:
        st.error(f"JSON Format Error: {exc}")
        st.stop()

    with st.spinner("Submitting…"):
        try:
            result = api_client.post_ingest(kb_type, data, base_url=base_url)
            st.success(f"✅ {result.get('message', 'Submission successful')}")
            st.json(result)
        except Exception as exc:
            st.error(f"Submission failed: {exc}")
