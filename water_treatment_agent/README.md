# Water Treatment Agent

A multi-agent + RAG system for water treatment process chain recommendation.
Given water quality parameters and constraints, the system recommends ranked treatment chains with evidence-backed explanations.

---

## Architecture

```
UserQuery
  └─► Task Parser Agent       → NormalizedQuery
        └─► Retrieval Agent   → RetrievalBundle (KB_unit / KB_template / KB_case)
              └─► Process Planning Agent → CandidatesBundle
                    └─► Constraint/Critic Agent → ConstraintReport
                          └─► Explanation Agent → FinalReport
```

## Project Structure

```
water_treatment_agent/
├── app/
│   ├── agents/          # 5 agents + prompt configs
│   ├── core/            # schemas, taxonomy, rules, config, logger
│   ├── rag/             # index builder, hybrid retriever, reranker
│   ├── api/             # FastAPI routes
│   ├── workflows/       # pipeline orchestrator
│   └── utils/           # scoring, evidence binding, normalization
├── data/
│   ├── taxonomy/        # taxonomy.json
│   ├── examples/        # sample input/output, eval test set
│   └── processed/       # built indexes (generated)
├── rag_data_json/       # knowledge base source files
├── scripts/             # build_indexes, run_demo, run_eval
├── tests/               # pytest tests
├── requirements.txt
└── .env.example
```

---

## Quick Start

### 1. Install dependencies

```bash
cd water_treatment_agent
python -m venv .venv

# macOS / Linux
source .venv/bin/activate

# Windows
.venv\Scripts\activate

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env and add your OPENROUTER_API_KEY
```

### 3. Build indexes

```bash
python scripts/build_indexes.py
```

### 4. Start the API

```bash
uvicorn app.api.main:app --reload --host 0.0.0.0 --port 8000
```

API docs available at: http://localhost:8000/docs

### 5. Run demo

```bash
python scripts/run_demo.py
```

### 6. Run tests

```bash
pytest tests/ -v
```

### 7. Run evaluation (Phase 4)

```bash
python scripts/run_eval.py
```

---

## API Endpoints

| Method | Path         | Description                        |
|--------|--------------|------------------------------------|
| GET    | /health      | Service health check               |
| POST   | /recommend   | Get Top-K treatment recommendations|
| POST   | /ingest      | Add new case/evidence to KB        |
| POST   | /evaluate    | Run evaluation on test set         |

### Example request

```bash
curl -X POST http://localhost:8000/recommend \
  -H "Content-Type: application/json" \
  -d @data/examples/example_input.json
```

---

## Development Roadmap

| Phase | Status | Description                                      |
|-------|--------|--------------------------------------------------|
| 1     | ✅ Done | Project structure + data schemas + mock data     |
| 2     | ✅ Done | Code skeleton + requirements + README            |
| 3     | 🔜 Next | LLM-backed agent logic + real retrieval          |
| 4     | 🔜     | Evaluation framework + metrics                   |
