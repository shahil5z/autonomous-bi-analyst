"""Number formatting shared by templates (GBP; the source shop is UK-based)."""

from __future__ import annotations


def money(v: float | None) -> str:
    if v is None:
        return "n/a"
    sign = "-" if v < 0 else ""
    v = abs(v)
    return f"{sign}£{v:,.0f}" if v >= 1000 else f"{sign}£{v:,.2f}"


def pct(v: float | None, signed: bool = True) -> str:
    if v is None:
        return "n/a"
    return f"{v:+.1f}%" if signed else f"{v:.1f}%"


def num(v: float | None, d: int = 0) -> str:
    if v is None:
        return "n/a"
    return f"{v:,.{d}f}"


def pval(p: float) -> str:
    return "< 0.001" if p < 0.001 else f"{p:.3f}"
