"""Water Treatment Agent GUI — Home page."""
import streamlit as st

from components import sidebar_config

st.set_page_config(
    page_title="Water Treatment Agent",
    page_icon="💧",
    layout="wide",
    initial_sidebar_state="expanded",
)

sidebar_config()

st.title("💧 Water Treatment Agent")
st.markdown(
    """
    This system is based on Retrieval-Augmented Generation (RAG) and multi-agent pipelines,
    providing scientifically sound treatment process chain recommendations for different water quality conditions.

    ---

    ### Function Navigation

    | Page | Description |
    |---|---|
    | **1 Recommend** | Input water quality parameters and constraints to get evidence-based treatment chain recommendations |
    | **2 Health** | View backend service, index, and LLM configuration status |
    | **3 Ingest** | Add new treatment units, templates, or case entries to the knowledge base |

    ---

    ### Quick Start

    1. In the **sidebar**, confirm the backend address (default `http://localhost:8000`)
    2. Navigate to the **1 Recommend** page and fill in the query (at least input contaminants or natural language description)
    3. Click "Get Recommendations" and wait for about 30–60 seconds

    > **Start the backend** (in the `water_treatment_agent/` directory):
    > ```
    > uvicorn app.api.main:app --reload --port 8000
    > ```
    """
)
