"""
FastAPI route definitions.

Endpoints
---------
GET  /health    — service health + index status + LLM configuration flag
POST /recommend — Top-K treatment chain recommendation (full pipeline)
POST /ingest    — Add new KB entry and rebuild indexes
POST /evaluate  — Run evaluation over a test set (Phase 4 stub)
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, HTTPException, status

from app.core.config import get_settings
from app.core.logger import get_logger
from app.core.schemas import (
    EvaluateRequest,
    EvaluateResponse,
    HealthResponse,
    IngestRequest,
    IngestResponse,
    RecommendRequest,
    RecommendResponse,
)
from app.workflows.pipeline import WaterTreatmentPipeline

logger = get_logger(__name__)
router = APIRouter()

_pipeline: WaterTreatmentPipeline | None = None


def _get_pipeline() -> WaterTreatmentPipeline:
    global _pipeline
    if _pipeline is None:
        _pipeline = WaterTreatmentPipeline()
    return _pipeline


def _rebuild_indexes() -> None:
    """Rebuild BM25 index in the background after ingest."""
    try:
        from app.rag.index_builder import IndexBuilder
        n = IndexBuilder().build_all()
        logger.info("Background index rebuild complete: %d chunks", n)
        # Invalidate retriever cache so next query reloads fresh index
        pipeline = _get_pipeline()
        pipeline._retriever._retriever._loaded = False
    except Exception as e:
        logger.error("Background index rebuild failed: %s", e)



@router.get(
    "/health",
    response_model=HealthResponse,
    tags=["system"],
    summary="Service health check",
)
def health_check() -> HealthResponse:
    """
    Returns service status including index state, chunk count,
    and whether an LLM API key is configured.
    """
    settings = get_settings()
    index_dir = settings.index_dir
    bm25_path = index_dir / "bm25_index.pkl"
    corpus_path = index_dir / "corpus.jsonl"

    indexes_loaded = bm25_path.exists()
    chunk_count = 0
    if corpus_path.exists():
        with open(corpus_path, "r", encoding="utf-8") as f:
            chunk_count = sum(1 for _ in f)

    return HealthResponse(
        status="ok",
        version="0.1.0",
        indexes_loaded=indexes_loaded,
        extra={
            "chunk_count": chunk_count,
            "llm_configured": bool(settings.openrouter_api_key),
            "default_model": settings.default_model,
            "index_dir": str(index_dir),
        },
    )


@router.post(
    "/recommend",
    response_model=RecommendResponse,
    tags=["core"],
    summary="Get Top-K water treatment recommendations",
)
def recommend(request: RecommendRequest) -> RecommendResponse:
    """
    Run the full 5-agent pipeline and return Top-K ranked treatment chain
    recommendations with evidence-bound explanations.

    **Request body example**
    ```json
    {
      "query": {
        "raw_query": "Rural groundwater, arsenic 150 µg/L, limited budget, no brine disposal",
        "source_water": "groundwater",
        "contaminants": ["arsenic"],
        "treatment_targets": {"arsenic_ug_L": 10, "compliance_standard": "WHO"},
        "constraints": {"budget": "low", "brine_disposal": false}
      },
      "top_k": 3
    }
    ```
    """
    t0 = time.perf_counter()
    try:
        pipeline = _get_pipeline()
        report = pipeline.run(request.query, top_k=request.top_k)
        elapsed = round(time.perf_counter() - t0, 2)
        logger.info(
            "/recommend query=%s recs=%d elapsed=%.2fs",
            report.query_id, len(report.recommendations), elapsed,
        )
        return RecommendResponse(
            query_id=report.query_id,
            status="success",
            recommendations=report.recommendations,
            pipeline_version=report.pipeline_version,
        )
    except Exception as e:
        logger.exception("Error in /recommend")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Pipeline error: {e}",
        )


@router.post(
    "/ingest",
    response_model=IngestResponse,
    tags=["data"],
    summary="Add new KB entry and rebuild indexes",
)
def ingest(
    request: IngestRequest,
    background_tasks: BackgroundTasks,
) -> IngestResponse:
    """
    Persist a new knowledge base entry (unit evidence, template, or case)
    and schedule an asynchronous index rebuild.

    **Request body example**
    ```json
    {
      "kb_type": "kb_case",
      "data": {
        "case_id": "CASE-005",
        "title": "My new case study",
        "contaminants": ["arsenic"],
        "treatment_chain": ["coagulation", "filtration", "chlorination"]
      }
    }
    ```
    """
    valid_kb_types = {"kb_unit", "kb_case"}
    if request.kb_type not in valid_kb_types:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"kb_type must be one of {valid_kb_types}, got '{request.kb_type}'",
        )

    try:
        settings = get_settings()
        rag_dir: Path = settings.data_dir / "ingest"
        rag_dir.mkdir(parents=True, exist_ok=True)

        entry_id = (
            request.data.get("id")
            or request.data.get("case_id")
            or "new_entry"
        )
        out_path = rag_dir / f"{request.kb_type}_{entry_id}.json"
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(request.data, f, ensure_ascii=False, indent=2)

        logger.info("/ingest: wrote %s, scheduling index rebuild", out_path.name)
        background_tasks.add_task(_rebuild_indexes)

        return IngestResponse(
            status="success",
            message=f"Saved to '{out_path.name}'. Index rebuild scheduled in background.",
            records_added=1,
        )
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /ingest")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Ingest error: {e}",
        )


@router.post(
    "/evaluate",
    response_model=EvaluateResponse,
    tags=["evaluation"],
    summary="Evaluate pipeline on a test set (Phase 4)",
)
def evaluate(request: EvaluateRequest) -> EvaluateResponse:
    """
    Runs evaluation metrics (Hit@K, Recall@K, MRR, nDCG, constraint violation
    rate, citation support rate) over a labelled test set.

    Full implementation in Phase 4 (`scripts/run_eval.py`).
    """
    return EvaluateResponse(
        status="not_implemented",
        metrics={
            "message": "Full evaluation implemented in Phase 4 (run_eval.py).",
            "test_cases_received": len(request.test_cases),
        },
    )
