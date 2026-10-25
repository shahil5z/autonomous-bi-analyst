"""Run the full data pipeline: ingest the UCI Online Retail II file, then build the DuckDB database."""

from __future__ import annotations

import gzip
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent

for step in ("ingest.py", "build_db.py"):
    print(f"==> {step}", flush=True)
    subprocess.run([sys.executable, str(HERE / step)], check=True)
# Compressed copy shipped with the API (Vercel). mtime=0 keeps the file byte-identical for identical input.
src = HERE.parent / "data" / "processed" / "abi.duckdb"
dst = HERE.parent / "backend" / "artifacts" / "abi.duckdb.gz"
dst.parent.mkdir(parents=True, exist_ok=True)
with open(src, "rb") as f_in, open(dst, "wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, compresslevel=9, mtime=0) as f_out:
    shutil.copyfileobj(f_in, f_out)
print(f"Pipeline complete: {src.relative_to(HERE.parent)} and {dst.relative_to(HERE.parent)}")
