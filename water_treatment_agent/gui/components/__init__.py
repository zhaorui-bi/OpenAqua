"""Shared sidebar helper for all pages."""
from __future__ import annotations

import streamlit as st

_DEFAULT_BACKEND = "http://localhost:8000"


def sidebar_config() -> str:
    """Render backend URL widget in sidebar; return the current base URL."""
    with st.sidebar:
        st.markdown("## ⚙️ Settings")
        if "backend_url" not in st.session_state:
            st.session_state["backend_url"] = _DEFAULT_BACKEND
        url = st.text_input(
            "Backend API Address",
            value=st.session_state["backend_url"],
        )
        st.session_state["backend_url"] = url
        st.caption("Startup command: `uvicorn app.api.main:app --reload`")
    return url
