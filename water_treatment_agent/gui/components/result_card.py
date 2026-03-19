"""Render a single RecommendationItem as a structured Streamlit section."""
from __future__ import annotations

import streamlit as st

from components.chain_viz import render_chain
from components.score_chart import render_score_chart

_STATUS_EMOJI = {
    "PASS": "✅", "WARNING": "⚠️", "WARN": "⚠️", "FAIL": "❌", "N/A": "➖",
}
_UNCERTAINTY_ICON = {
    "low": "🟢", "low-medium": "🟡", "medium": "🟡",
    "high": "🔴", "insufficient_evidence": "🔴",
}
_SUPPORT_BADGE = {
    "evidence_backed":  ("🔵", "evidence_backed"),
    "system_inference": ("🟡", "system_inference"),
    "assumption":       ("🟠", "assumption"),
}


def render_result_card(rec: dict, index: int) -> None:
    """Render one RecommendationItem."""
    rank        = rec.get("rank", index + 1)
    chain       = rec.get("chain", [])
    score_obj   = rec.get("rank_score", {})
    total       = score_obj.get("total", 0.0)
    uncertainty = rec.get("uncertainty", "medium")
    chain_id    = rec.get("chain_id", "—")

    st.markdown("---")


    h_col, s_col = st.columns([4, 1])
    with h_col:
        st.markdown(f"### #{rank} Recommendation")
        st.caption(f"Chain ID: `{chain_id}`  ·  "
                   f"Uncertainty: {_UNCERTAINTY_ICON.get(uncertainty, '⚪')} {uncertainty}")
    with s_col:
        st.metric("Overall Score", f"{total:.3f}")


    if chain:
        st.plotly_chart(
            render_chain(chain),
            use_container_width=True,
            key=f"chain_{rank}_{index}",
        )

    sc_col, why_col = st.columns([1, 2])
    with sc_col:
        st.plotly_chart(
            render_score_chart(score_obj),
            use_container_width=True,
            key=f"score_{rank}_{index}",
        )
    with why_col:
        why = rec.get("why_it_works", "")
        if why:
            st.markdown("**Why It Works**")
            st.markdown(why)

    risks       = rec.get("risks", [])
    assumptions = rec.get("assumptions", [])
    if risks or assumptions:
        r_col, a_col = st.columns(2)
        with r_col:
            if risks:
                st.markdown("**Risks**")
                for item in risks:
                    st.markdown(f"- {item}")
        with a_col:
            if assumptions:
                st.markdown("**Assumptions**")
                for item in assumptions:
                    st.markdown(f"- {item}")


    evidence = rec.get("evidence", [])
    if evidence:
        with st.expander(f"Evidence Citations ({len(evidence)} items)"):
            for ev in evidence:
                sup_type = ev.get("support_type", "assumption")
                emoji, label = _SUPPORT_BADGE.get(sup_type, ("⚪", sup_type))
                excerpt = (ev.get("text_excerpt") or "")[:300]
                st.markdown(
                    f"{emoji} **{label}** — {ev.get('claim', '')}\n\n"
                    f"> {excerpt}\n\n"
                    f"- Source: `{ev.get('source_id', '—')}`"
                )
                st.divider()


    constraint_report = rec.get("constraint_report") or {}
    checks = constraint_report.get("checks", [])
    if checks:
        with st.expander(f"Constraint Checks ({len(checks)} items)"):
            for ck in checks:
                status  = ck.get("status", "N/A")
                emoji   = _STATUS_EMOJI.get(status, "➖")
                rule_id = ck.get("rule_id", "")
                msg     = ck.get("message", "")
                st.markdown(f"{emoji} **{rule_id}** — {msg}")
