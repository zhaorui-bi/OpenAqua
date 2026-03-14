"""Tests for Pydantic schemas."""
import pytest
from app.core.schemas import UserQuery, WaterQuality, TreatmentTargets, UserConstraints


def test_user_query_minimal():
    q = UserQuery(source_water="groundwater", contaminants=["arsenic"])
    assert q.source_water == "groundwater"
    assert "arsenic" in q.contaminants


def test_water_quality_extra_fields():
    wq = WaterQuality(pH=7.2, arsenic_ug_L=150, extra={"selenium_ug_L": 5})
    assert wq.pH == 7.2
    assert wq.extra["selenium_ug_L"] == 5


def test_rank_score_bounds():
    from app.core.schemas import RankScore
    score = RankScore(
        total=0.75,
        coverage_score=0.80,
        constraint_score=0.90,
        evidence_score=0.60,
        risk_penalty=-0.10,
    )
    assert 0 <= score.total <= 1
