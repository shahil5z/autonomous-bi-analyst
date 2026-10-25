"""Question Analyzer: natural language -> validated ParsedQuestion.

1. Safety screen (destructive / injection-style requests are refused).
2. Follow-up resolution against session context.
3. Deterministic keyword/regex parser.
4. OpenAI structured-output parser only when the deterministic parser is unsure.
Every LLM field is validated and re-resolved against the real data.
"""

from __future__ import annotations

import re

from app.agent import periods as P
from app.agent.context import SessionState
from app.agent.schemas import Filter, LLMQuestionParse, ParsedQuestion
from app.database.connection import data_range, distinct_values

UNSUPPORTED_TOPICS = [
    (r"\b(profit|margin|margins|cost of goods|cogs|costs?)\b", "The dataset has sales prices but no cost data, so profit or margin cannot be calculated."),
    (r"\bdiscount", "The dataset has no discount or promotion-price field, so the effect of discounts cannot be measured."),
    (r"\b(weather|temperature|rain)\b", "There is no weather data in the database."),
    (r"\b(employee|staff|salary|salaries|headcount)\b", "There is no employee data in the database."),
    (r"\b(competitor|market share|stock price|share price)\b", "There is no competitor or market data in the database."),
    (r"\b(inventory|stock level|stockout)\b", "There is no inventory data in the database."),
    (r"\b(email address|phone number|home address|name of (the )?customer)\b", "Personal customer details are not available and would not be shared."),
    (r"\b(marketing spend|ad spend|roi|return on investment|budget)\b", "There is no marketing spend data, so ROI cannot be calculated."),
]
INJECTION = re.compile(
    r"(ignore (all |any )?(previous|prior|above) (instructions|prompts?)|system prompt|you are now|disregard (the|your) (rules|instructions)|"
    r"\b(drop|delete|truncate|alter|insert|update)\s+(table|from|into|the)\b|\bdrop\s+\w+\s+table|reveal (your|the) (key|prompt|instructions)|api key|shell command|rm -rf)",
    re.IGNORECASE,
)
FOLLOW_UP_CUES = re.compile(r"\b(that|this|those|these|it|there|same|them|its)\b|^\s*(and|what about|how about)\b", re.IGNORECASE)
METRIC_WORDS = [("quantity", r"\b(units|quantity|volume|demand)\b"), ("orders", r"\b(orders|invoices|transactions)\b"),
                ("customers", r"\b(customers|buyers)\b(?!.*segment)")]
REGION_ALIASES = {"uk": "United Kingdom", "britain": "United Kingdom", "ireland": "EIRE", "eire": "EIRE", "usa": "USA",
                  "us": "USA", "america": "USA"}


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip())


def find_entities(text: str) -> dict[str, list[str]]:
    t = " " + text.lower() + " "
    found: dict[str, list[tuple[int, str]]] = {"region": [], "country": [], "category": []}
    for dim, table in [("region", "sales"), ("country", "sales")]:
        for v in distinct_values(table, dim):
            i = t.find(" " + v.lower())
            if i >= 0 and re.search(r"\b" + re.escape(v.lower()) + r"\b", t):
                found[dim].append((i, v))
    for alias, canon in REGION_ALIASES.items():
        m = re.search(r"\b" + alias + r"\b", t)
        if m:
            dim = "region" if canon == "United Kingdom" else "country"
            if canon not in [v for _, v in found[dim]]:
                found[dim].append((m.start(), canon))
    for v in distinct_values("products", "category"):
        if v != "Other" and v.lower() in t:
            found["category"].append((t.find(v.lower()), v))
    # a country equal to a region name (United Kingdom) counts as the region
    found["country"] = [(i, v) for i, v in found["country"] if v not in {r for _, r in found["region"]}]
    return {k: [v for _, v in sorted(vals)] for k, vals in found.items()}


def _metric(t: str) -> str:
    for name, pat in METRIC_WORDS:
        if re.search(pat, t):
            return name
    return "revenue"


def _campaign_entity(t: str) -> list[str]:
    m = re.search(r"\bcmp\s?0?([1-8])\b|\bcampaign\s*#?\s*0?([1-8])\b", t)
    if m:
        return [f"CMP0{m.group(1) or m.group(2)}"]
    from app.database.connection import execute

    for cid, name in execute("SELECT campaign_id, name FROM campaigns").itertuples(index=False):
        theme = name.lower().replace(" campaign", "")
        first = theme.split(" email")[0].split(" social")[0].split(" catalogue")[0].split(" website")[0]
        if first and re.search(r"\b" + re.escape(first) + r"\b", t):
            return [cid]
    return []


FILTERABLE = {"metric_total", "revenue_ranking", "growth_ranking", "period_change", "drivers", "top_products", "trend"}


def deterministic_parse(question: str, ctx: SessionState | None = None) -> tuple[ParsedQuestion, bool]:
    """Return (parsed, confident)."""
    q = _norm(question)
    t = q.lower()
    lo, hi = data_range()
    found = P.find_periods(t, hi)
    ents = find_entities(t)
    metric = _metric(t)
    base = {"metrics": [metric], "parser": "deterministic"}

    if INJECTION.search(t):
        return ParsedQuestion(intent="unsupported", requires_visualization=False,
                              unsupported_reason="This analyst is read-only and only answers analytical questions. "
                                                 "Instructions to change data, reveal configuration or ignore rules are not followed.",
                              **base), True
    for pat, reason in UNSUPPORTED_TOPICS:
        if re.search(pat, t):
            return ParsedQuestion(intent="unsupported", unsupported_reason=reason, requires_visualization=False, **base), True

    filters: list[Filter] = []
    if ents["region"] and not re.search(r"\bcompare|\bvs\b|versus|difference between|significant", t):
        filters.append(Filter(dimension="region", values=ents["region"][:3]))
    if ents["country"] and not re.search(r"\bcompare|\bvs\b|versus|difference between|significant", t):
        filters.append(Filter(dimension="country", values=ents["country"][:3]))
    if ents["category"]:
        filters.append(Filter(dimension="category", values=ents["category"][:3]))

    # ---- follow-ups
    if ctx and ctx.last_parsed and (FOLLOW_UP_CUES.search(t) or len(t.split()) <= 4):
        last = ctx.last_parsed
        if re.search(r"\b(products?|items?|categor(y|ies))\b", t) and re.search(r"\b(drove|drive|driving|behind|caus|contribut|explain|why|responsible)", t):
            cur = last.time_period or P.latest_complete_quarter(hi)
            prev = last.comparison_period
            if prev is None:
                if cur.label[-2] == "Q":
                    prev = P.previous_quarter(cur)
                elif len(cur.label) == 4:
                    prev = P.year(int(cur.label) - 1)
                else:
                    y, mth = int(cur.label[:4]), int(cur.label[5:])
                    prev = P.month(y, mth - 1) if mth > 1 else P.month(y - 1, 12)
            f = list(last.filters)
            if ctx.focus_entity and ctx.focus_dimension in ("region", "country"):
                f = [x for x in f if x.dimension != ctx.focus_dimension] + [Filter(dimension=ctx.focus_dimension, values=[ctx.focus_entity])]
            return ParsedQuestion(intent="drivers", time_period=cur, comparison_period=prev, filters=f,
                                  dimensions=["product", "category"], entities=[ctx.focus_entity] if ctx.focus_entity else [],
                                  is_follow_up=True, metrics=last.metrics, parser="deterministic"), True
        if re.search(r"\b(over time|trend|by month|monthly)\b", t):
            f = list(last.filters)
            if ctx.focus_entity and ctx.focus_dimension in ("region", "country"):
                f = [Filter(dimension=ctx.focus_dimension, values=[ctx.focus_entity])]
            return ParsedQuestion(intent="trend", filters=f, metrics=last.metrics, is_follow_up=True,
                                  parser="deterministic"), True
        if re.match(r"^\s*(and |what about|how about)", t) and (filters or found):
            if filters and last.intent not in FILTERABLE:
                return ParsedQuestion(intent="unsupported", requires_visualization=False, is_follow_up=True,
                                      unsupported_reason=f"The previous analysis ({last.intent.replace('_', ' ')}) runs on total sales only; "
                                                         "region, country and category filters are not supported for it in Phase 1.",
                                      **base), True
            if filters and last.intent == "growth_ranking":
                return ParsedQuestion(intent="period_change", dimensions=["region", "product"], filters=filters,
                                      time_period=found[-1] if found else last.time_period, comparison_period=last.comparison_period,
                                      metrics=last.metrics, is_follow_up=True, parser="deterministic"), True
            if filters and last.intent == "revenue_ranking":
                return ParsedQuestion(intent="metric_total", filters=filters, time_period=found[-1] if found else last.time_period,
                                      metrics=last.metrics, is_follow_up=True, parser="deterministic"), True
            upd = last.model_copy(deep=True)
            if filters:
                upd.filters = filters
            if found:
                upd.time_period = found[-1]
            upd.is_follow_up = True
            return upd, True

    def periods_two(default_prev) -> tuple:
        if len(found) >= 2:
            a, b = sorted(found[:2], key=lambda p: p.start)
            return b, a
        cur = found[0] if found else P.latest_complete_quarter(hi)
        if cur.label[-2] == "Q":
            return cur, default_prev(cur)
        if len(cur.label) == 4:
            return cur, P.year(int(cur.label) - 1)
        y, mth = int(cur.label[:4]), int(cur.label[5:])
        return cur, P.month(y - 1, mth) if default_prev is P.same_quarter_last_year else (P.month(y, mth - 1) if mth > 1 else P.month(y - 1, 12))

    if re.search(r"\b(forecast|predict|projection|project(ed)? |next \d+ days|next (month|week))", t):
        m = re.search(r"next\s+(\d{1,4})\s*(day|week|month|year)", t)
        horizon = 30
        if m:
            n, unit = int(m.group(1)), m.group(2)
            horizon = n * {"day": 1, "week": 7, "month": 30, "year": 365}[unit]
        elif "next week" in t:
            horizon = 7
        elif re.search(r"next (year|\w+ years)", t):
            horizon = 365
        if horizon > 90:
            return ParsedQuestion(intent="unsupported", requires_visualization=False,
                                  unsupported_reason=f"A {horizon}-day forecast is beyond what about two years of daily history can support (max 90 days).",
                                  **base), True
        return ParsedQuestion(intent="forecast", horizon_days=horizon, **base), True
    if re.search(r"\b(anomal|outlier|spike|unusual|abnormal)", t):
        return ParsedQuestion(intent="anomaly", **base), True
    if re.search(r"\b(campaign|promotion|promo)", t):
        return ParsedQuestion(intent="campaign_effect", entities=_campaign_entity(t), **base), True
    if re.search(r"\b(segment|cluster|rfm|most valuable customers?|customer groups?|valuable customers?)", t):
        return ParsedQuestion(intent="segment_value", **base), True
    if re.search(r"\b(correlat|relationship between (price|unit price)|price and (quantity|units|demand)|elasticity)", t):
        return ParsedQuestion(intent="correlation", requires_visualization=True, **base), True
    if re.search(r"\b(associat|category mix|product mix|chi[- ]square|independen)", t):
        return ParsedQuestion(intent="association", time_period=found[0] if found else None, **base), True
    two = ents["region"] if len(ents["region"]) >= 2 else ents["country"] if len(ents["country"]) >= 2 else []
    if two and re.search(r"\b(compare|vs|versus|difference|significant|differ)", t):
        dim = "region" if two is ents["region"] else "country"
        return ParsedQuestion(intent="compare_groups", entities=two[:2], dimensions=[dim],
                              time_period=found[0] if found else None, **base), True
    if re.search(r"\b(significant|statistically)", t):
        return ParsedQuestion(intent="unsupported", requires_visualization=False,
                              unsupported_reason="Please name the two regions or countries to compare (e.g. 'Is the difference between "
                                                 "Western Europe and Northern Europe statistically significant?').", **base), True
    if re.search(r"\b(grew|grow|growth|growing|fastest)\b", t):
        dim = "country" if "countr" in t else "category" if "categor" in t else "product" if "product" in t else "region"
        cur, prev = periods_two(P.same_quarter_last_year)
        return ParsedQuestion(intent="growth_ranking", dimensions=[dim], time_period=cur, comparison_period=prev,
                              filters=filters, **base), True
    if re.search(r"\b(change|changed|decline|declined|drop|dropped|fall|fell|increase|increased|decrease|went up|went down)\b", t):
        cur, prev = periods_two(P.previous_quarter)
        return ParsedQuestion(intent="period_change", dimensions=["region", "product"], time_period=cur,
                              comparison_period=prev, filters=filters, **base), True
    m = re.search(r"\btop\s*(\d{1,2})\b", t)
    if re.search(r"\b(products?|items?|best[- ]selling|bestsellers?)\b", t) and re.search(r"\b(top|best|most|driv|highest|leading|popular)", t):
        return ParsedQuestion(intent="top_products", dimensions=["product"], top_n=min(int(m.group(1)), 25) if m else 5,
                              time_period=found[0] if found else None, filters=filters, **base), True
    if re.search(r"\b(trend|over time|monthly|by month|per month|seasonal|seasonality)\b", t):
        return ParsedQuestion(intent="trend", filters=filters, **base), True
    if re.search(r"\b(how many|how much|total|number of)\b", t) and not re.search(r"\b(by|per|each|which)\b", t):
        return ParsedQuestion(intent="metric_total", time_period=found[0] if found else None, filters=filters, **base), True
    if re.search(r"\b(highest|most|lowest|least|largest|biggest|top|rank|breakdown|by region|by country|by category|which region|which country|which category|show)\b", t):
        dim = "country" if "countr" in t else "category" if "categor" in t else "region"
        return ParsedQuestion(intent="revenue_ranking", dimensions=[dim], top_n=min(int(m.group(1)), 25) if m else 10,
                              time_period=found[0] if found else None,
                              filters=[f for f in filters if f.dimension != dim], **base), True
    return ParsedQuestion(intent="unsupported", requires_visualization=False,
                          unsupported_reason="I couldn't map this question to an analysis I support with the available data.",
                          **base), False


def from_llm(raw: LLMQuestionParse, question: str) -> ParsedQuestion:
    """Validate and resolve an LLM parse against real periods and entity values."""
    _, hi = data_range()
    cur = P.parse_label(raw.time_period, hi)
    prev = P.parse_label(raw.comparison_period, hi)
    filters = []
    known_regions = {v.lower(): v for v in distinct_values("sales", "region")}
    known_countries = {v.lower(): v for v in distinct_values("sales", "country")}
    regions = [known_regions[r.lower()] for r in raw.filter_regions if r.lower() in known_regions]
    countries = [known_countries[c.lower()] for c in raw.filter_countries if c.lower() in known_countries]
    if regions:
        filters.append(Filter(dimension="region", values=regions[:3]))
    if countries:
        filters.append(Filter(dimension="country", values=countries[:3]))
    intent = raw.intent
    entities = [e for e in raw.entities if e.lower() in known_regions or e.lower() in known_countries or re.fullmatch(r"CMP0[1-8]", e)]
    if intent in ("growth_ranking", "period_change", "drivers"):
        cur = cur or P.latest_complete_quarter(hi)
        prev = prev or (P.same_quarter_last_year(cur) if intent == "growth_ranking" and cur.label[-2] == "Q"
                        else P.previous_quarter(cur) if cur.label[-2] == "Q" else None)
        if prev is None:
            intent = "unsupported"
    if intent == "compare_groups" and len(entities) < 2:
        entities = (regions + countries)[:2]
        filters = []
    horizon = raw.horizon_days
    if intent == "forecast":
        horizon = horizon or 30
        if not 1 <= horizon <= 90:
            return ParsedQuestion(intent="unsupported", parser="openai", requires_visualization=False,
                                  unsupported_reason="Forecast horizons above 90 days are not supported.")
    return ParsedQuestion(
        intent=intent, metrics=raw.metrics or ["revenue"], dimensions=list(dict.fromkeys(raw.dimensions)),
        time_period=cur, comparison_period=prev, filters=filters, entities=entities[:4],
        top_n=max(1, min(raw.top_n or 5, 25)), horizon_days=horizon if intent == "forecast" else None,
        requires_visualization=raw.requires_visualization, parser="openai",
        unsupported_reason=(raw.unsupported_reason or "The question cannot be answered with the available data.")
        if intent == "unsupported" else None,
    )
