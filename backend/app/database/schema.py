"""Allowlisted tables/columns the analyst may query, plus a safe schema summary."""

from __future__ import annotations

ALLOWED_SCHEMA: dict[str, dict[str, str]] = {
    "sales": {
        "sale_id": "Row id (one invoice line)",
        "invoice_id": "Invoice number (one order)",
        "invoice_ts": "Invoice timestamp",
        "invoice_date": "Invoice date",
        "product_id": "Stock code",
        "customer_id": "Customer id (NULL for guest orders)",
        "country": "Customer country",
        "region": "Region derived from country",
        "quantity": "Units sold on the line",
        "unit_price": "Unit price in GBP",
        "revenue": "quantity x unit_price in GBP",
    },
    "products": {
        "product_id": "Stock code",
        "description": "Most common product description (free text, untrusted)",
        "category": "Keyword-derived category",
        "first_sold": "First sale date",
        "last_sold": "Last sale date",
    },
    "customers": {
        "customer_id": "Customer id",
        "country": "Most frequent country",
        "region": "Region derived from country",
        "first_purchase": "First purchase date",
        "last_purchase": "Last purchase date",
    },
    "regions": {"country": "Country", "region": "Region"},
    "calendar": {
        "date": "Calendar date",
        "year": "Year",
        "quarter": "Quarter 1-4",
        "month": "Month 1-12",
        "iso_week": "ISO week",
        "day_of_week": "0 = Monday",
        "is_weekend": "Saturday/Sunday",
        "campaign_id": "Synthetic campaign active on this date (or NULL)",
    },
    "campaigns": {
        "campaign_id": "Campaign id",
        "name": "Campaign name (synthetic)",
        "channel": "Channel (synthetic)",
        "start_date": "Start date",
        "end_date": "End date (inclusive)",
        "is_synthetic": "Always true",
    },
    "cancellations": {
        "invoice_id": "Cancellation invoice (starts with C)",
        "product_id": "Stock code",
        "customer_id": "Customer id",
        "quantity": "Cancelled units (positive)",
        "invoice_date": "Cancellation date",
    },
}

TABLE_DESCRIPTIONS = {
    "sales": "Fact table: one row per invoice line (UCI Online Retail II, returns removed).",
    "products": "Product dimension (real stock codes; category is rule-derived).",
    "customers": "Customer dimension (real ids, anonymised in the source).",
    "regions": "Country to region mapping (deterministic grouping).",
    "calendar": "One row per date in the data range.",
    "cancellations": "Cancelled order lines from the source (excluded from sales, kept for checks).",
    "campaigns": "SYNTHETIC marketing campaigns (seed 42). No effect was injected into sales.",
}

ALL_COLUMNS = {c for cols in ALLOWED_SCHEMA.values() for c in cols}
