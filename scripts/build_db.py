"""Step 2: clean the raw data and build the analyst's DuckDB star schema.

Public (real) data: sales lines, products, customers, countries, dates.
Derived (deterministic rules): region grouping of countries, product category from
description keywords, calendar attributes.
Synthetic (seed 42): campaigns. No campaign effect is injected into sales.
"""

from __future__ import annotations

import re
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PARQUET = ROOT / "data" / "raw" / "online_retail_ii.parquet"
DB = ROOT / "data" / "processed" / "abi.duckdb"
SEED = 42

REGIONS = {
    "United Kingdom": ["United Kingdom"],
    "Western Europe": ["EIRE", "France", "Germany", "Netherlands", "Belgium", "Switzerland",
                       "Austria", "Channel Islands", "Luxembourg"],
    "Northern Europe": ["Norway", "Sweden", "Denmark", "Finland", "Iceland"],
    "Southern Europe": ["Spain", "Portugal", "Italy", "Greece", "Cyprus", "Malta"],
    "Eastern Europe": ["Poland", "Lithuania", "Czech Republic"],
}
COUNTRY_TO_REGION = {c: r for r, cs in REGIONS.items() for c in cs}

CATEGORY_RULES = [
    ("Seasonal", r"CHRISTMAS|XMAS|EASTER|ADVENT|HALLOWEEN|SANTA|REINDEER"),
    ("Bags & Storage", r"\bBAG\b|BAGS|STORAGE|TIN\b|TINS|BOX\b|BOXES|BASKET|JAR\b|HOLDER"),
    ("Lighting & Candles", r"CANDLE|LIGHT|LANTERN|T-LIGHT|LAMP|NIGHT LIGHT"),
    ("Kitchen & Dining", r"MUG|CUP|PLATE|BOWL|TEA|CAKE|BAKING|JUG|NAPKIN|SPOON|LUNCH|BOTTLE|COASTER|APRON|KITCHEN"),
    ("Stationery & Gift Wrap", r"CARD|WRAP|PAPER|NOTEBOOK|PENCIL|PEN\b|STICKER|RIBBON|TAPE|ENVELOPE|CHALK"),
    ("Toys & Kids", r"TOY|GAME|DOLL|CHILDREN|CHILDS|KIDS|PLAYHOUSE|SPACEBOY|DOLLY|JIGSAW|SKITTLES"),
    ("Jewellery & Accessories", r"NECKLACE|BRACELET|EARRING|RING\b|HAIR|PURSE|UMBRELLA|BROOCH|JEWEL"),
    ("Home Decor", r"SIGN|FRAME|CLOCK|MIRROR|CUSHION|HEART|DECORATION|ORNAMENT|GARLAND|BUNTING|VASE|DOORMAT|WALL|HANGING"),
]


def categorise(desc: str) -> str:
    d = (desc or "").upper()
    for name, pattern in CATEGORY_RULES:
        if re.search(pattern, d):
            return name
    return "Other"


def clean(raw: pd.DataFrame) -> tuple[pd.DataFrame, dict]:
    stats = {"raw_rows": len(raw)}
    df = raw.rename(columns={"Invoice": "invoice_id", "StockCode": "product_id", "Description": "description",
                             "Quantity": "quantity", "InvoiceDate": "invoice_ts", "Price": "unit_price",
                             "Customer ID": "customer_id", "Country": "country"})
    df = df.drop_duplicates()
    stats["after_dedup"] = len(df)
    df = df[~df["invoice_id"].astype(str).str.startswith("C")]
    df = df[(df["quantity"] > 0) & (df["unit_price"] > 0)]
    stats["after_removing_returns_and_nonpositive"] = len(df)
    df = df[df["product_id"].astype(str).str.match(r"^\d{5}")]
    stats["after_removing_non_product_codes"] = len(df)
    df["product_id"] = df["product_id"].astype(str).str.upper()
    df["customer_id"] = df["customer_id"].astype("Int64")
    df["country"] = df["country"].replace({"EIRE": "EIRE"})
    df["region"] = df["country"].map(COUNTRY_TO_REGION).fillna("Rest of World")
    df["invoice_date"] = df["invoice_ts"].dt.normalize()
    df["revenue"] = (df["quantity"] * df["unit_price"]).round(2)
    return df, stats


def cancellations_table(raw: pd.DataFrame) -> pd.DataFrame:
    """Cancelled lines (invoice starts with 'C') kept separately so tools can flag cancelled orders."""
    c = raw[raw["Invoice"].astype(str).str.startswith("C") & raw["StockCode"].astype(str).str.match(r"^\d{5}")].copy()
    out = pd.DataFrame({"invoice_id": c["Invoice"].astype(str), "product_id": c["StockCode"].astype(str).str.upper(),
                        "customer_id": c["Customer ID"].astype("Int64"), "quantity": c["Quantity"].abs(),
                        "invoice_date": c["InvoiceDate"].dt.normalize()})
    return out.drop_duplicates().reset_index(drop=True)


def build() -> None:
    raw = pd.read_parquet(PARQUET)
    df, stats = clean(raw)
    cancellations = cancellations_table(raw)

    desc = (df.dropna(subset=["description"]).groupby(["product_id", "description"]).size()
            .reset_index(name="n").sort_values(["product_id", "n"], ascending=[True, False])
            .drop_duplicates("product_id")[["product_id", "description"]])
    products = (df.groupby("product_id").agg(first_sold=("invoice_date", "min"), last_sold=("invoice_date", "max"))
                .reset_index().merge(desc, on="product_id", how="left"))
    products["description"] = products["description"].fillna("UNKNOWN").str.strip()
    products["category"] = products["description"].map(categorise)

    cust = df.dropna(subset=["customer_id"])
    country_mode = (cust.groupby(["customer_id", "country"]).size().reset_index(name="n")
                    .sort_values(["customer_id", "n"], ascending=[True, False]).drop_duplicates("customer_id"))
    customers = (cust.groupby("customer_id").agg(first_purchase=("invoice_date", "min"),
                                                 last_purchase=("invoice_date", "max")).reset_index()
                 .merge(country_mode[["customer_id", "country"]], on="customer_id"))
    customers["region"] = customers["country"].map(COUNTRY_TO_REGION).fillna("Rest of World")

    regions = (df.groupby(["country", "region"]).size().reset_index(name="_n").drop(columns="_n"))

    dates = pd.date_range(df["invoice_date"].min(), df["invoice_date"].max(), freq="D")
    calendar = pd.DataFrame({"date": dates})
    calendar["year"] = calendar["date"].dt.year
    calendar["quarter"] = calendar["date"].dt.quarter
    calendar["month"] = calendar["date"].dt.month
    calendar["iso_week"] = calendar["date"].dt.isocalendar().week.astype(int)
    calendar["day_of_week"] = calendar["date"].dt.day_of_week  # 0 = Monday
    calendar["is_weekend"] = calendar["day_of_week"] >= 5

    # Synthetic campaigns: non-overlapping windows, seed 42, no effect injected.
    rng = np.random.default_rng(SEED)
    channels = ["Email", "Social media", "Catalogue", "Website banner"]
    themes = ["Loyalty", "Free delivery", "Bundle offer", "Newsletter", "Gift guide", "Clearance", "New range",
              "Spring range"]
    campaigns, cursor, i = [], dates[0] + pd.Timedelta(days=30), 0
    while i < 8:
        start = cursor + pd.Timedelta(days=int(rng.integers(20, 70)))
        length = int(rng.integers(7, 22))
        end = start + pd.Timedelta(days=length - 1)
        if end > dates[-1] - pd.Timedelta(days=14):
            break
        campaigns.append({"campaign_id": f"CMP{i + 1:02d}", "name": f"{themes[i]} {channels[i % 4].lower()} campaign",
                          "channel": channels[i % 4], "start_date": start, "end_date": end, "is_synthetic": True})
        cursor, i = end, i + 1
    campaigns = pd.DataFrame(campaigns)
    calendar["campaign_id"] = None
    for c in campaigns.itertuples():
        mask = (calendar["date"] >= c.start_date) & (calendar["date"] <= c.end_date)
        calendar.loc[mask, "campaign_id"] = c.campaign_id

    sales = df[["invoice_id", "invoice_ts", "invoice_date", "product_id", "customer_id", "country", "region",
                "quantity", "unit_price", "revenue"]].reset_index(drop=True)
    sales.insert(0, "sale_id", np.arange(1, len(sales) + 1))

    DB.parent.mkdir(parents=True, exist_ok=True)
    if DB.exists():
        DB.unlink()
    con = duckdb.connect(str(DB))
    for name, frame in [("sales", sales), ("products", products), ("customers", customers),
                        ("regions", regions), ("calendar", calendar), ("campaigns", campaigns),
                        ("cancellations", cancellations)]:
        con.register("tmp", frame)
        con.execute(f"CREATE TABLE {name} AS SELECT * FROM tmp")
        con.unregister("tmp")
    con.execute("ALTER TABLE sales ALTER invoice_date TYPE DATE")
    con.execute("ALTER TABLE calendar ALTER date TYPE DATE")
    con.execute("ALTER TABLE cancellations ALTER invoice_date TYPE DATE")
    con.execute("ALTER TABLE campaigns ALTER start_date TYPE DATE")
    con.execute("ALTER TABLE campaigns ALTER end_date TYPE DATE")
    for col in ["first_sold", "last_sold"]:
        con.execute(f"ALTER TABLE products ALTER {col} TYPE DATE")
    for col in ["first_purchase", "last_purchase"]:
        con.execute(f"ALTER TABLE customers ALTER {col} TYPE DATE")
    for name in ["sales", "products", "customers", "regions", "calendar", "campaigns", "cancellations"]:
        print(f"{name:10s} {con.execute(f'SELECT COUNT(*) FROM {name}').fetchone()[0]:>9,} rows")
    con.close()
    for k, v in stats.items():
        print(f"{k}: {v:,}")


if __name__ == "__main__":
    build()
