"""Streamlit form for building a water treatment recommendation query."""
from __future__ import annotations

import streamlit as st

_SOURCE_WATER_OPTS = [
    "", "groundwater", "surface water", "brackish water",
    "municipal tap", "wastewater", "stormwater",
]
_ENERGY_OPTS   = ["", "low", "low-medium", "medium", "medium-high", "high"]
_SKILL_OPTS    = ["", "low", "medium", "high"]
_BUDGET_OPTS   = ["", "low", "medium", "high", "unlimited"]


def render_query_form() -> dict | None:
    """
    Render the full query input form inside a st.form block.

    Returns the API payload dict on submit, or None if not yet submitted.
    """
    with st.form("query_form", border=True):
        st.subheader("🔍 Query Input")

        raw_query = st.text_area(
            "Natural Language Description (Optional)",
            placeholder="e.g., Groundwater with high arsenic levels, need to treat to drinking water standards, limited budget, no专业 operators...",
            height=85,
        )
        col1, col2 = st.columns(2)
        with col1:
            source_water = st.selectbox("Source Water Type", _SOURCE_WATER_OPTS)
        with col2:
            context = st.text_input("Additional Context", placeholder="e.g., Rural area, non-specialized operators")

        st.markdown("**Contaminants** (comma-separated)")
        contaminants_raw = st.text_input(
            "Contaminants",
            label_visibility="collapsed",
            placeholder="e.g., Arsenic, Nitrate, E. coli",
        )
        contaminants = [c.strip() for c in contaminants_raw.split(",") if c.strip()]


        with st.expander("📊 Inlet Water Quality Parameters (Optional)"):
            wq1, wq2, wq3 = st.columns(3)
            with wq1:
                ph         = st.number_input("pH",            0.0, 14.0, 7.0, 0.1)
                turbidity  = st.number_input("Turbidity (NTU)",    0.0, value=0.0)
                arsenic    = st.number_input("Arsenic (µg/L)",     0.0, value=0.0)
                nitrate    = st.number_input("Nitrate (mg/L)", 0.0, value=0.0)
            with wq2:
                fluoride   = st.number_input("Fluoride (mg/L)", 0.0, value=0.0)
                toc        = st.number_input("TOC (mg/L)",    0.0, value=0.0)
                iron       = st.number_input("Iron (mg/L)",     0.0, value=0.0)
            with wq3:
                hardness   = st.number_input("Hardness (mg/L)",   0.0, value=0.0)
                ecoli      = st.number_input("E. coli (CFU/100mL)", 0.0, value=0.0)
                lead       = st.number_input("Lead (µg/L)",     0.0, value=0.0)


        with st.expander("🎯 Treatment Targets (Optional)"):
            tg1, tg2 = st.columns(2)
            with tg1:
                tgt_arsenic  = st.number_input("Target Arsenic (µg/L)",      0.0, value=10.0)
                tgt_nitrate  = st.number_input("Target Nitrate (mg/L)",  0.0, value=0.0)
                tgt_fluoride = st.number_input("Target Fluoride (mg/L)",  0.0, value=0.0)
            with tg2:
                tgt_turbidity = st.number_input("Target Turbidity (NTU)",    0.0, value=0.0)
                tgt_toc       = st.number_input("Target TOC (mg/L)",   0.0, value=0.0)
                compliance    = st.text_input("Compliance Standard", placeholder="e.g., EPA, WHO, GB 5749")


        with st.expander("⚙️ Constraints and Preferences (Optional)"):
            ct1, ct2 = st.columns(2)
            with ct1:
                budget         = st.selectbox("Budget Level",       _BUDGET_OPTS)
                energy         = st.selectbox("Energy Constraint",       _ENERGY_OPTS)
                operator_skill = st.selectbox("Operator Skill Level",   _SKILL_OPTS)
            with ct2:
                use_for_drinking    = st.checkbox("Use for Drinking Water",     value=True)
                brine_disposal      = st.checkbox("Allow Brine Disposal", value=True)
                chemical_dosing     = st.checkbox("Allow Chemical Dosing",   value=True)
                footprint           = st.checkbox("Footprint Constraint",       value=False)

        top_k = st.slider("Number of Recommendations", min_value=1, max_value=5, value=3)
        submitted = st.form_submit_button("🚀 Get Recommendations", use_container_width=True, type="primary")

    if not submitted:
        return None

    water_quality: dict = {}
    if ph != 7.0:    water_quality["pH"]                = ph
    if turbidity:    water_quality["turbidity"]          = turbidity
    if arsenic:      water_quality["arsenic_ug_L"]       = arsenic
    if nitrate:      water_quality["nitrate_mg_L"]       = nitrate
    if fluoride:     water_quality["fluoride_mg_L"]      = fluoride
    if toc:          water_quality["toc_mg_L"]           = toc
    if iron:         water_quality["iron_mg_L"]          = iron
    if hardness:     water_quality["hardness_mg_L"]      = hardness
    if ecoli:        water_quality["e_coli_CFU_100mL"]   = ecoli
    if lead:         water_quality["lead_ug_L"]          = lead

    targets: dict = {}
    if tgt_arsenic:   targets["arsenic_ug_L"]       = tgt_arsenic
    if tgt_nitrate:   targets["nitrate_mg_L"]       = tgt_nitrate
    if tgt_fluoride:  targets["fluoride_mg_L"]      = tgt_fluoride
    if tgt_turbidity: targets["turbidity_NTU"]      = tgt_turbidity
    if tgt_toc:       targets["toc_mg_L"]           = tgt_toc
    if compliance:    targets["compliance_standard"] = compliance

    constraints: dict = {
        "brine_disposal":        brine_disposal,
        "use_for_drinking":      use_for_drinking,
        "chemical_dosing_allowed": chemical_dosing,
    }
    if footprint:
        constraints["footprint_constraint"] = "constrained"
    if budget:         constraints["budget"]         = budget
    if energy:         constraints["energy"]         = energy
    if operator_skill: constraints["operator_skill"] = operator_skill

    query: dict = {"constraints": constraints}
    if raw_query:    query["raw_query"]         = raw_query
    if source_water: query["source_water"]      = source_water
    if contaminants: query["contaminants"]      = contaminants
    if context:      query["context"]           = context
    if water_quality: query["water_quality"]    = water_quality
    if targets:      query["treatment_targets"] = targets

    return {"query": query, "top_k": top_k}
