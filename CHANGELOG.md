# Changelog

## [v1.0.0](https://github.com/zhaorui-bi/OpenAqua/releases/tag/v1.0.0) — 2026-08-15

First public release of OpenAqua.

### Framework

- Five-agent pipeline: Parser, Retriever, Planner, Critic, and Explainer
- Hybrid retrieval over unit-level TDB records and case-level plant reports
- Taxonomy-constrained process units
- Constraint critic with auto-revision for missing disinfection and brine conflicts
- Interpretable ranking: coverage, constraint fit, evidence support, and risk
- Rule- and template-based fallback when no LLM key is set

### Interfaces

- FastAPI: `GET /health`, `POST /recommend`, `POST /ingest`
- Streamlit GUI for recommend, health, and ingest
- OpenRouter LLM backend with optional model overrides

### Data and evaluation

- Knowledge assets and WContBench hosted at [huggingface.co/datasets/zhaorui-bi/OpenAqua](https://huggingface.co/datasets/zhaorui-bi/OpenAqua)
- WContBench: 337 cases (Easy 92 / Middle 117 / Difficult 128)
- `test_openaqua.py`: Precision, Recall, F1, Coverage, Hit Rate, CLA
- `test_retrieval.py`: Precision@k, Recall@k, Hit@k

### Repository

- Public homepage with authors, framework figure, and citation
- Data removed from git; download from Hugging Face
