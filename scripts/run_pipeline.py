"""Run the full data pipeline: ingest the UCI Online Retail II file, then build the DuckDB database."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

for step in ("ingest.py", "build_db.py"):
    print(f"==> {step}", flush=True)
    subprocess.run([sys.executable, str(HERE / step)], check=True)
print("Pipeline complete: data/processed/abi.duckdb")
