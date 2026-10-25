"""Pydantic contracts shared by the analyzer, planner, tools and API."""

from __future__ import annotations

from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

Intent = Literal[
    "metric_total", "revenue_ranking", "growth_ranking", "top_products", "period_change", "drivers", "trend",
    "segment_value", "anomaly", "campaign_effect", "forecast", "compare_groups", "association",
    "correlation", "unsupported",
]
Metric = Literal["revenue", "quantity", "orders", "customers"]
Dimension = Literal["region", "country", "product", "category"]

INTENT_DESCRIPTIONS: dict[str, str] = {
    "metric_total": "A single total of a metric for a period (e.g. how many orders in November 2011).",
    "revenue_ranking": "Rank a metric by region/country/category (e.g. highest revenue region).",
    "growth_ranking": "Period-over-period growth by a dimension (e.g. fastest growing region).",
    "top_products": "Top-N products by a metric.",
    "period_change": "How a metric changed between two periods and which regions/products contributed.",
    "drivers": "Which products/categories drove a change inside one region (usually a follow-up).",
    "trend": "Monthly trend of a metric over time.",
    "segment_value": "Customer segmentation (RFM + K-Means) and the most valuable segment.",
    "anomaly": "Largest anomaly in daily revenue and its contributing regions/products.",
    "campaign_effect": "Compare sales during synthetic campaign periods vs other days (observational).",
    "forecast": "Forecast daily revenue for the next N days (max 90).",
    "compare_groups": "Statistically compare order values between two regions/countries.",
    "association": "Chi-square test: is product category mix associated with region?",
    "correlation": "Correlation between product unit price and units sold.",
    "unsupported": "The data cannot answer the question.",
}


class Period(BaseModel):
    label: str
    start: date
    end: date  # exclusive

    @model_validator(mode="after")
    def _check(self) -> Period:
        if self.end <= self.start:
            raise ValueError("period end must be after start")
        return self


class Filter(BaseModel):
    dimension: Dimension
    values: list[str] = Field(min_length=1, max_length=10)


class ParsedQuestion(BaseModel):
    intent: Intent
    metrics: list[Metric] = Field(default_factory=lambda: ["revenue"])
    dimensions: list[Dimension] = Field(default_factory=list)
    time_period: Period | None = None
    comparison_period: Period | None = None
    filters: list[Filter] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    top_n: int = Field(default=5, ge=1, le=25)
    horizon_days: int | None = Field(default=None, ge=1, le=90)
    requires_visualization: bool = True
    is_follow_up: bool = False
    unsupported_reason: str | None = None
    parser: Literal["deterministic", "openai"] = "deterministic"
    parser_note: str | None = None

    @field_validator("metrics")
    @classmethod
    def _metrics(cls, v: list[str]) -> list[str]:
        return v or ["revenue"]


class LLMQuestionParse(BaseModel):
    """Schema the LLM must fill. Periods are labels resolved deterministically afterwards."""

    intent: Intent
    metrics: list[Metric]
    dimensions: list[Dimension]
    time_period: str | None = Field(description="e.g. '2011-Q3', '2011', '2011-03', or null")
    comparison_period: str | None = Field(description="Same format as time_period, or null")
    filter_regions: list[str]
    filter_countries: list[str]
    entities: list[str]
    top_n: int | None
    horizon_days: int | None
    requires_visualization: bool
    unsupported_reason: str | None
    # (all fields are required-but-nullable so the schema works with strict structured outputs)


class PlanStep(BaseModel):
    tool: str
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    description: str


class Plan(BaseModel):
    intent: Intent
    summary: str
    steps: list[PlanStep]
    human_steps: list[str]
    statistical_test: bool = False
    chart: bool = False


class SQLRecord(BaseModel):
    purpose: str
    sql: str
    params: list[Any] = Field(default_factory=list)
    display_sql: str
    row_count: int


class ChartSpec(BaseModel):
    type: Literal["line", "bar", "area", "scatter", "histogram", "box", "heatmap"]
    title: str
    x: str
    y: list[str]
    data: list[dict[str, Any]]
    x_label: str | None = None
    y_label: str | None = None
    note: str | None = None


class ToolResult(BaseModel):
    tool: str
    ok: bool
    data: dict[str, Any] = Field(default_factory=dict)
    rows: list[dict[str, Any]] = Field(default_factory=list)
    sql: list[SQLRecord] = Field(default_factory=list)
    method: str = ""
    limitations: list[str] = Field(default_factory=list)
    error: str | None = None
    no_answer: bool = False


class ValidationCheck(BaseModel):
    name: str
    passed: bool
    detail: str = ""


class Evidence(BaseModel):
    question: str
    status: Literal["answered", "no_answer", "error"]
    analysis_type: str
    method: str
    headline: dict[str, Any] = Field(default_factory=dict)
    supporting_data: list[dict[str, Any]] = Field(default_factory=list)
    columns: list[str] = Field(default_factory=list)
    stats: dict[str, Any] = Field(default_factory=dict)
    sql: list[SQLRecord] = Field(default_factory=list)
    periods: dict[str, str] = Field(default_factory=dict)
    tables: list[str] = Field(default_factory=list)
    chart: ChartSpec | None = None
    limitations: list[str] = Field(default_factory=list)
    validation: list[ValidationCheck] = Field(default_factory=list)
    no_answer_reason: str | None = None
    tools_used: list[str] = Field(default_factory=list)


class Explanation(BaseModel):
    answer: str
    evidence_bullets: list[str]
    analysis: str
    limitations: list[str]
    follow_ups: list[str]


class GroundingReport(BaseModel):
    passed: bool
    unmatched_numbers: list[str] = Field(default_factory=list)
    causal_language: list[str] = Field(default_factory=list)


class TraceStep(BaseModel):
    label: str
    status: Literal["done", "skipped", "failed"]
    detail: str = ""


class LineageStep(BaseModel):
    stage: str
    detail: str


class AnalyzeRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    session_id: str | None = Field(default=None, max_length=64, pattern=r"^[A-Za-z0-9_-]*$")
    use_openai: bool = True


class AnalyzeResponse(BaseModel):
    run_id: str
    session_id: str
    question: str
    parsed: ParsedQuestion
    plan: Plan
    evidence: Evidence
    explanation: Explanation
    explanation_source: Literal["openai", "template"]
    explanation_note: str | None = None
    grounding: GroundingReport
    follow_ups: list[str]
    trace: list[TraceStep]
    lineage: list[LineageStep]
    openai_calls: int
    duration_ms: int
