"""Page 2 — Backend health & status."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import streamlit as st

import api_client
from components import sidebar_config

st.set_page_config(page_title="System Status", page_icon="🩺", layout="centered")

base_url = sidebar_config()

st.title("🩺 System Status")

if st.button("🔄 Refresh", type="primary"):
    pass  # triggers re-run

try:
    health = api_client.get_health(base_url)
    status = health.get("status", "unknown")

    if status == "ok":
        st.success(f"✅ Service is running  (v{health.get('version', '?')})")
    else:
        st.error(f"❌ Service is not running：{status}")

    extra = health.get("extra", {})

    m1, m2, m3 = st.columns(3)
    m1.metric("Index Status",    "✅ Loaded" if health.get("indexes_loaded") else "❌ Not Loaded")
    m2.metric("Chunk Count",  extra.get("chunk_count", 0))
    m3.metric("LLM Configured", "✅" if extra.get("llm_configured") else "❌")

    st.markdown("---")
    st.markdown(f"**Default Model**: `{extra.get('default_model', '—')}`")
    st.markdown(f"**Index Directory**: `{extra.get('index_dir', '—')}`")
    st.markdown(f"**Current Backend**: `{base_url}`")

except Exception as exc:
    st.error(f"Failed to connect to backend: {exc}")
    st.info("Please ensure the backend is running and check the API URL in the sidebar.")
