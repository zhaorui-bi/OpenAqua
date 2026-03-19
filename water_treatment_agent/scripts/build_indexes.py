"""
Build retrieval indexes from rag_data_json/.

Usage:
    python scripts/build_indexes.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.rag.index_builder import IndexBuilder


def main() -> None:
    builder = IndexBuilder()
    builder.build_all()
    print("Indexes built successfully.")


if __name__ == "__main__":
    main()
