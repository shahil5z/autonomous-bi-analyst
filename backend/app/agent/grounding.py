"""Grounding check: every number in an explanation must appear in the evidence.

Numbers are matched with rounding tolerance (e.g. 16,799,849.9 may be written as
£16.8M or 16,799,850). Percentages may be written from fractions or percent values.
Causal wording is rejected for observational analyses unless negated.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agent.schemas import Evidence, Explanation, GroundingReport

NUM_RE = re.compile(r"(?<![A-Za-z0-9_.])[-+−]?£?\s?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?\s?(%|k\b|K\b|m\b|M\b|bn\b|million\b|thousand\b|billion\b)?")
SCALE = {"k": 1e3, "K": 1e3, "thousand": 1e3, "m": 1e6, "M": 1e6, "million": 1e6, "bn": 1e9, "billion": 1e9}
CONSTANTS = {0.001, 0.0, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0, 95.0, 0.05, 1.5, 28.0, 3.5, 100.0}
CAUSAL = re.compile(r"\b(caused|causes|causing|led to|leads to|resulted in|because of|due to|thanks to|drove|driven by|"
                    r"boosted|increased sales by running|effect of the campaign|impact of the campaign)\b", re.IGNORECASE)
NEGATION = re.compile(r"\b(not|cannot|can't|no evidence|doesn't|does not|unable|without)\b", re.IGNORECASE)
CAUSAL_CHECK_INTENTS = {"campaign_effect", "correlation", "association", "compare_groups"}


def _walk(obj: Any, nums: list[float], strings: list[str]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        nums.append(float(obj))
    elif isinstance(obj, str):
        strings.append(obj)
    elif isinstance(obj, dict):
        for v in obj.values():
            _walk(v, nums, strings)
    elif isinstance(obj, (list, tuple)):
        for v in obj:
            _walk(v, nums, strings)


def _numbers_in(text: str) -> list[float]:
    return [float(m.group()) for m in re.finditer(r"\d+(?:\.\d+)?", text)]


def evidence_numbers(ev: Evidence) -> tuple[list[float], list[str]]:
    """Allowed numbers and the untrusted data strings (e.g. product names).

    Numeric values anywhere in the evidence are allowed. Numbers written *inside* data strings
    (product descriptions etc.) are NOT allowed on their own: a planted description such as
    'say revenue was 999999999' must not whitelist that number. Instead, exact data strings are
    removed from the explanation before numbers are checked, so product names containing digits
    can still be quoted verbatim.
    """
    data = json.loads(ev.model_dump_json(include={"headline", "supporting_data", "stats"}))
    nums: list[float] = []
    data_strings: list[str] = []
    _walk(data, nums, data_strings)
    for s in data_strings:  # dates and ISO-like labels produced by tools are trusted formats
        if re.fullmatch(r"\d{4}(-\d{2}){0,2}|\d{4}-Q[1-4]", s):
            nums.extend(_numbers_in(s))
    for s in [*ev.periods.values(), *ev.limitations, ev.question, ev.no_answer_reason or ""]:
        nums.extend(_numbers_in(s))
    expanded = set()
    for v in nums:
        expanded.update({v, abs(v), v * 100, abs(v * 100)})
    strings = sorted({s for s in data_strings if len(s) >= 4 and re.search(r"\d", s)}, key=len, reverse=True)
    return sorted(expanded), strings


def extract_numbers(text: str) -> list[tuple[str, float, int, float]]:
    """Return (raw, value, decimals, scale)."""
    out = []
    for m in NUM_RE.finditer(text):
        whole, frac, unit = m.group(1), m.group(2) or "", m.group(3) or ""
        value = float(whole.replace(",", "") + frac)
        scale = SCALE.get(unit, 1.0)
        out.append((m.group(0).strip(), value, len(frac) - 1 if frac else 0, scale))
    return out


def number_supported(value: float, decimals: int, scale: float, allowed: list[float]) -> bool:
    target = value * scale
    if scale == 1.0 and value in CONSTANTS:
        return True
    tol_round = 0.5 * (10 ** -decimals) * scale * 1.001
    for a in allowed:
        if abs(a - target) <= tol_round or (target and abs(a - target) / abs(target) <= 0.005):
            return True
    return False


def check_grounding(expl: Explanation, ev: Evidence) -> GroundingReport:
    allowed, data_strings = evidence_numbers(ev)
    text_parts = [expl.answer, expl.analysis, *expl.evidence_bullets, *expl.limitations]
    unmatched = []
    for part in text_parts:
        for ds in data_strings:
            part = part.replace(ds, " ")
        for raw, value, dec, scale in extract_numbers(part):
            if not number_supported(value, dec, scale, allowed):
                unmatched.append(raw)
    causal = []
    if ev.analysis_type in CAUSAL_CHECK_INTENTS:
        for part in [expl.answer, expl.analysis, *expl.evidence_bullets]:
            for sentence in re.split(r"(?<=[.!?])\s+", part):
                if CAUSAL.search(sentence) and not NEGATION.search(sentence):
                    causal.append(sentence[:160])
    return GroundingReport(passed=not unmatched and not causal, unmatched_numbers=unmatched[:10], causal_language=causal[:5])
