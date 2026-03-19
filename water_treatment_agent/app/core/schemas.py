"""
Pydantic schemas for all inter-agent data contracts.
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, Field

class EnergyLevel(str, Enum):
    LOW = "low"
    LOW_MEDIUM = "low-medium"
    MEDIUM = "medium"
    MEDIUM_HIGH = "medium-high"
    HIGH = "high"


class UncertaintyLevel(str, Enum):
    LOW = "low"
    LOW_MEDIUM = "low-medium"
    MEDIUM = "medium"
    HIGH = "high"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class CheckStatus(str, Enum):
    PASS = "PASS"
    WARN = "WARNING"
    FAIL = "FAIL"
    NA = "N/A"

##
class WaterQuality(BaseModel):
    """Raw water quality measurements."""
    pH: Optional[float] = None
    turbidity_NTU: Optional[float] = None
    arsenic_ug_L: Optional[float] = None
    nitrate_mg_L: Optional[float] = None
    fluoride_mg_L: Optional[float] = None
    toc_mg_L: Optional[float] = None
    iron_mg_L: Optional[float] = None
    hardness_mg_L: Optional[float] = None
    e_coli_CFU_100mL: Optional[float] = None
    lead_ug_L: Optional[float] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class TreatmentTargets(BaseModel):
    """Desired effluent quality targets."""
    arsenic_ug_L: Optional[float] = None
    nitrate_mg_L: Optional[float] = None
    fluoride_mg_L: Optional[float] = None
    turbidity_NTU: Optional[float] = None
    toc_mg_L: Optional[float] = None
    e_coli: Optional[str] = None  # e.g. "non_detectable"
    compliance_standard: Optional[str] = None  # "WHO", "GB5749", "EU", "USEPA"
    extra: Dict[str, Any] = Field(default_factory=dict)


class UserConstraints(BaseModel):
    """Hard and soft constraints from the user."""
    budget: Optional[str] = None          # "low" | "medium" | "high"
    energy: Optional[str] = None          # "limited" | "grid_connected"
    brine_disposal: Optional[bool] = None # False = brine disposal NOT available
    operator_skill: Optional[str] = None  # "low" | "medium" | "high"
    use_for_drinking: Optional[bool] = None
    footprint_constraint: Optional[str] = None
    chemical_dosing_allowed: Optional[bool] = None
    extra: Dict[str, Any] = Field(default_factory=dict)


class UserQuery(BaseModel):
    """Raw user query — system entry point."""
    query_id: Optional[str] = None
    raw_query: Optional[str] = None
    source_water: Optional[str] = None
    water_quality: Optional[WaterQuality] = None
    contaminants: Optional[List[str]] = Field(default_factory=list)
    treatment_targets: Optional[TreatmentTargets] = None
    constraints: Optional[UserConstraints] = None
    context: Optional[str] = None


##
class NormalizedQuery(BaseModel):
    """Structured, normalized query output from Task Parser Agent."""
    query_id: str
    source_water: str
    water_quality: WaterQuality
    contaminants: List[str]           # normalized IDs from taxonomy
    treatment_targets: TreatmentTargets
    constraints: UserConstraints
    context: Optional[str] = None
    missing_fields: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    normalization_notes: List[str] = Field(default_factory=list)


class RetrievedChunk(BaseModel):
    """A single retrieved evidence chunk."""
    source_id: str            # e.g. "tdb_arsenic_properties"
    chunk_id: str             # unique ID within source
    relevance_score: float    # 0-1 combined score
    bm25_score: Optional[float] = None
    embedding_score: Optional[float] = None
    coverage_tags: List[str] = Field(default_factory=list)  # e.g. ["arsenic", "coagulation"]
    text: str
    metadata: Dict[str, Any] = Field(default_factory=dict)


class RetrievalBundle(BaseModel):
    """Aggregated retrieval results from all three KBs."""
    query_id: str
    kb_unit: List[RetrievedChunk] = Field(default_factory=list)
    kb_case: List[RetrievedChunk] = Field(default_factory=list)
    total_retrieved: int = 0


class CandidateChain(BaseModel):
    """A single candidate treatment chain."""
    chain_id: str
    chain: List[str]              # ordered list of unit processes from taxonomy
    key_units: List[str]          # most critical units
    rationale: str                # brief planning rationale
    energy_intensity: Optional[EnergyLevel] = None
    generates_brine: bool = False
    requires_disinfection: bool = False


class CandidatesBundle(BaseModel):
    """All candidate chains from the Planning Agent."""
    query_id: str
    candidates: List[CandidateChain]
    planning_notes: List[str] = Field(default_factory=list)


class UnitCheckResult(BaseModel):
    """Per-constraint check result."""
    rule_id: str
    rule_description: str
    status: CheckStatus
    violated_by: Optional[str] = None  # chain_id or unit name
    message: str


class ChainConstraintReport(BaseModel):
    """Constraint check results for one candidate chain."""
    chain_id: str
    overall_status: CheckStatus
    checks: List[UnitCheckResult]
    revision_actions: List[str] = Field(default_factory=list)


class ConstraintReport(BaseModel):
    """Full constraint evaluation for all candidates."""
    query_id: str
    chain_reports: List[ChainConstraintReport]
    chains_to_revise: List[str] = Field(default_factory=list)
    chains_to_drop: List[str] = Field(default_factory=list)



class RankScore(BaseModel):
    """Decomposed, interpretable ranking score."""
    total: float = Field(ge=0, le=1)
    coverage_score: float = Field(ge=0, le=1)
    constraint_score: float = Field(ge=0, le=1)
    evidence_score: float = Field(ge=0, le=1)
    risk_penalty: float = Field(ge=-1, le=0)
    score_breakdown: Dict[str, float] = Field(default_factory=dict)


class EvidenceCitation(BaseModel):
    """A single piece of evidence bound to a claim."""
    chunk_id: str
    source_id: str
    claim: str
    support_type: str  # "evidence_backed" | "system_inference" | "assumption"
    text_excerpt: str


class RecommendationItem(BaseModel):
    """Full recommendation entry for one process chain."""
    rank: int
    chain_id: str
    chain: List[str]
    rank_score: RankScore
    why_it_works: str
    evidence: List[EvidenceCitation]
    assumptions: List[str]
    risks: List[str]
    retrieved_cases: List[str]
    constraint_report: ChainConstraintReport
    uncertainty: UncertaintyLevel


class FinalReport(BaseModel):
    """Final output of the entire pipeline."""
    query_id: str
    normalized_query: NormalizedQuery
    recommendations: List[RecommendationItem]
    system_notes: List[str] = Field(default_factory=list)
    pipeline_version: str = "0.1.0"


##
class RecommendRequest(BaseModel):
    query: UserQuery
    top_k: int = Field(default=3, ge=1, le=10)


class RecommendResponse(BaseModel):
    query_id: str
    status: str
    recommendations: List[RecommendationItem]
    pipeline_version: str = "0.1.0"


class IngestRequest(BaseModel):
    kb_type: str  # "kb_unit" | "kb_case"
    data: Dict[str, Any]


class IngestResponse(BaseModel):
    status: str
    message: str
    records_added: int = 0


class EvaluateRequest(BaseModel):
    test_cases: List[Dict[str, Any]]
    top_k: int = 3


class EvaluateResponse(BaseModel):
    status: str
    metrics: Dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    version: str
    indexes_loaded: bool
    extra: Dict[str, Any] = Field(default_factory=dict)
