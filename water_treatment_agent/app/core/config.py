"""
Central configuration loaded from environment variables via pydantic-settings.
"""
from __future__ import annotations

from pathlib import Path
from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    openrouter_api_key: str = Field(default="", alias="OPENROUTER_API_KEY")
    openrouter_base_url: str = "https://openrouter.ai/api/v1"
    default_model: str = "anthropic/claude-3-haiku"
    planner_model: str = "anthropic/claude-3.5-sonnet"
    explanation_model: str = "anthropic/claude-3.5-sonnet"
    llm_temperature: float = 0.2
    llm_max_tokens: int = 2048

    project_root: Path = Path(__file__).parent.parent.parent
    data_dir: Optional[Path] = None        # resolved in model_post_init
    index_dir: Optional[Path] = None
    unit_kb_dir: Optional[Path] = None     # real unit-level tdb directory
    taxonomy_path: Optional[Path] = None   # real taxonomy.json path
    case_kb_json: Optional[Path] = None    # structured case KB (optional, post-ETL)

    def model_post_init(self, __context: object) -> None:
        if self.data_dir is None:
            object.__setattr__(self, "data_dir", self.project_root / "data")
        if self.index_dir is None:
            object.__setattr__(self, "index_dir", self.project_root / "data" / "processed" / "indexes")
        if self.unit_kb_dir is None:
            object.__setattr__(self, "unit_kb_dir", self.project_root / "data" / "unit-level" / "tdb")
        if self.taxonomy_path is None:
            object.__setattr__(self, "taxonomy_path", self.project_root / "data" / "unit-level" / "taxonomy.json")
        if self.case_kb_json is None:
            object.__setattr__(self, "case_kb_json", self.project_root / "data" / "case-level" / "kb_cases.json")

    top_k_retrieval: int = 10
    top_k_rerank: int = 5
    bm25_weight: float = 0.4
    embedding_weight: float = 0.6
    embedding_model: str = "sentence-transformers/all-MiniLM-L6-v2"

    top_k_recommendations: int = 3
    max_planning_candidates: int = 5
    max_critic_iterations: int = 2

    api_host: str = "0.0.0.0"
    api_port: int = 8000
    api_debug: bool = False

    log_level: str = "INFO"
    log_dir: Optional[Path] = None


_settings: Optional[Settings] = None


def get_settings() -> Settings:
    """Return the module-level Settings singleton."""
    global _settings
    if _settings is None:
        _settings = Settings()
    return _settings
