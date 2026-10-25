"""Step 1: obtain the raw UCI Online Retail II file and cache it as parquet.

Source: UCI Machine Learning Repository, "Online Retail II" (id 502), CC BY 4.0.
https://archive.ics.uci.edu/dataset/502/online+retail+ii

If a local copy of the original .xlsx exists (set ABI_RAW_XLSX, or the sibling
Market Intelligence Lab cache), it is copied instead of downloading again. Only the
raw file is reused; no code from any other project is imported.
"""

from __future__ import annotations

import io
import os
import shutil
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

ROOT = Path(__file__).resolve().parents[1]
RAW_DIR = ROOT / "data" / "raw"
XLSX = RAW_DIR / "online_retail_II.xlsx"
PARQUET = RAW_DIR / "online_retail_ii.parquet"
UCI_ZIP_URL = "https://archive.ics.uci.edu/static/public/502/online+retail+ii.zip"
LOCAL_CANDIDATES = [
    os.getenv("ABI_RAW_XLSX", ""),
    str(ROOT.parent / "market-intelligence-lab" / "data" / "raw" / "online_retail_II.xlsx"),
]


def obtain_xlsx() -> None:
    if XLSX.exists():
        print(f"raw file present: {XLSX.name}")
        return
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    for cand in LOCAL_CANDIDATES:
        if cand and Path(cand).is_file():
            shutil.copyfile(cand, XLSX)
            print(f"copied raw file from local cache: {cand}")
            return
    print(f"downloading {UCI_ZIP_URL}")
    resp = requests.get(UCI_ZIP_URL, timeout=300)
    resp.raise_for_status()
    with zipfile.ZipFile(io.BytesIO(resp.content)) as zf:
        name = next(n for n in zf.namelist() if n.endswith(".xlsx"))
        XLSX.write_bytes(zf.read(name))


def to_parquet() -> None:
    if PARQUET.exists():
        print(f"parquet cache present: {PARQUET.name}")
        return
    print("reading both Excel sheets (takes a few minutes)...")
    sheets = pd.read_excel(XLSX, sheet_name=None, dtype={"Invoice": str, "StockCode": str})
    df = pd.concat(sheets.values(), ignore_index=True)
    df["Description"] = df["Description"].astype("string")
    df.to_parquet(PARQUET, index=False)
    print(f"wrote {PARQUET.name}: {len(df):,} rows")


if __name__ == "__main__":
    obtain_xlsx()
    to_parquet()
    sys.exit(0)
