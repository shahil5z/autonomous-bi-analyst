# Data

## Source and licence

**UCI Online Retail II**, Chen, D. (2019), UCI Machine Learning Repository, https://doi.org/10.24432/C5CG6D,
licence **CC BY 4.0**. A UK-based, non-store online retailer selling mainly gift-ware, many customers wholesalers.
Two sheets, 2009-12-01 to 2011-12-09, 1,067,371 rows in total.

`scripts/run_pipeline.py` downloads the zip from UCI (or uses `ABI_RAW_XLSX`), writes `data/raw/online_retail_ii.parquet`
and builds `data/processed/abi.duckdb`. Both folders are git-ignored; nothing from the dataset is committed.

## Public vs derived vs synthetic

| Part | Status |
|---|---|
| Invoices, products, quantities, prices, customer ids, countries | Public (from the dataset) |
| `region` | Derived: fixed country-to-region map |
| `category` | Derived: keyword rules on the product description ("Other" when no rule matches, 1,213 of 4,708 products) |
| `campaigns`, `calendar.campaign_id` | **Synthetic**: 8 non-overlapping windows, seed 42, no sales effect injected |

## Cleaning

1. Drop exact duplicate rows.
2. Remove cancellations (invoice starts with `C`) from sales; keep them in `cancellations`.
3. Keep lines with quantity > 0 and unit price > 0.
4. Keep product stock codes that start with five digits (drops postage, fees, manual adjustments, bank charges).
5. `revenue = quantity × unit_price` (GBP, 2 dp).

Result: 1,003,214 sales lines. 22.6% of lines have no customer id (guest orders); they count toward revenue but not
toward customer analyses.

## Tables

| Table | Rows | Grain |
|---|---|---|
| sales | 1,003,214 | invoice line |
| products | 4,708 | stock code |
| customers | 5,852 | customer id |
| regions | 43 | country |
| calendar | 739 | date (2009-12-01 to 2011-12-09) |
| campaigns | 8 | synthetic campaign |
| cancellations | 17,912 | cancelled product line |

## Data dictionary

| Table.column | Meaning |
|---|---|
| sales.sale_id | Row id |
| sales.invoice_id | Invoice number (one order) |
| sales.invoice_ts / invoice_date | Invoice timestamp / date |
| sales.product_id | Stock code |
| sales.customer_id | Customer id, NULL for guest orders |
| sales.country / region | Customer country / derived region |
| sales.quantity, unit_price, revenue | Units, GBP unit price, GBP line revenue |
| products.description | Most common description for the code (free text; treated as untrusted data) |
| products.category | Keyword-derived category |
| products.first_sold / last_sold | First and last sale date |
| customers.country / region | Most frequent country / region |
| customers.first_purchase / last_purchase | Dates |
| calendar.year, quarter, month, iso_week | Date parts |
| calendar.day_of_week | 0 = Monday |
| calendar.is_weekend | Saturday or Sunday (the shop rarely trades on Saturdays) |
| calendar.campaign_id | Synthetic campaign active that day, or NULL |
| campaigns.name, channel, start_date, end_date, is_synthetic | Synthetic campaign attributes (end inclusive; is_synthetic always true) |
| cancellations.invoice_id, product_id, customer_id, quantity, invoice_date | Cancelled lines (quantity positive) |

## Known quirks

- Cancelled orders are removed from sales rather than netted against the original order, so an order that was later
  cancelled still counts as revenue. Example: invoice 581483 on 2011-12-09 (£168,469.60) was cancelled by C581484 the
  same day; it drives the largest daily anomaly.
- The last day (2011-12-09) is partial and is excluded from forecasting.
