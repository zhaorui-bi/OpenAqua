"""Page 1 — Water treatment recommendation."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure gui/ root is on sys.path when Streamlit runs this page directly
sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

import api_client
from components import sidebar_config
from components.query_form import render_query_form
from components.result_card import render_result_card

st.set_page_config(
    page_title="Recommendation",
    page_icon="🔍",
    layout="wide",
)

base_url = sidebar_config()

st.title("🔍 Water Treatment Recommendation")
st.caption("Fill out the form below to get recommended treatment processes based on the knowledge base and evidence citations.")

payload = render_query_form()

if payload is not None:
    with st.spinner("Analyzing, please wait (LLM reasoning may take 30–60 seconds)…"):
        try:
            result = api_client.post_recommend(payload, base_url=base_url)
        except Exception as exc:
            st.error(f"Request failed: {exc}")
            st.stop()

    recs = result.get("recommendations", [])
    if not recs:
        st.warning("No recommendations returned. Please check your query or backend logs.")
    else:
        st.success(
            f"Query ID: `{result.get('query_id', '—')}` "
            f"| Total Recommendations: {len(recs)} "
            f"| Pipeline v{result.get('pipeline_version', '?')}"
        )
        for i, rec in enumerate(recs):
            render_result_card(rec, i)
