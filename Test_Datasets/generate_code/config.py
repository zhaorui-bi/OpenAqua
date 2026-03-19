"""
Global configuration for dataset generation pipeline.
Fill in OPENROUTER_API_KEY before running.
"""

import os

OPENROUTER_API_KEY = "YOUR_API_KEY_HERE"   # <-- fill in your key
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
MODEL = "openai/gpt-5.4"

BASE_DIR       = r"d:\WR-agent"  # <-- fill in your base directory
TEST_DATA_DIR  = os.path.join(BASE_DIR, "test_data")
GENERATE_DIR   = os.path.join(BASE_DIR, "test_data/generate_dataset")

TAXONOMY_PATH  = os.path.join(TEST_DATA_DIR, "data", "unit-level", "taxonomy.json")
KB_CASES_PATH  = os.path.join(TEST_DATA_DIR, "data", "case-level", "kb_cases.json")

OUTPUT_DIRS = {
    "easy":      os.path.join(TEST_DATA_DIR, "WContBench_Easy"),
    "middle":    os.path.join(TEST_DATA_DIR, "WContBench_Middle"),
    "difficult": os.path.join(TEST_DATA_DIR, "WContBench_Difficult"),
}


FEW_SHOT_PATHS = {
    "easy":      os.path.join(TEST_DATA_DIR, "WContBench_Easy",      "WContBench_E_001.json"),
    "middle":    os.path.join(TEST_DATA_DIR, "WContBench_Middle",    "WContBench_M_001.json"),
    "difficult": os.path.join(TEST_DATA_DIR, "WContBench_Difficult", "WContBench_D_001.json"),
}


GENERATION_TARGETS = {
    "easy":      {"total": 92,  "start_idx": 2},   # E_002 … E_092
    "middle":    {"total": 117, "start_idx": 2},   # M_002 … M_117
    "difficult": {"total": 128, "start_idx": 2},   # D_002 … D_128
}


MAX_TOKENS    = 8192
TEMPERATURE   = 0.7
MAX_RETRIES   = 3          # per-case retry attempts
CONCURRENCY   = 5          # max simultaneous API requests
RETRY_DELAY   = 2.0        # base seconds for exponential back-off


PROGRESS_FILE = os.path.join(GENERATE_DIR, "progress.json")
FAILED_FILE   = os.path.join(GENERATE_DIR, "failed_cases.json")
