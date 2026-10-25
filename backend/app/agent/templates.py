"""Deterministic explanation templates (used without OpenAI or when grounding fails)."""

from __future__ import annotations

import re

from app.agent.formatting import money, num, pct, pval
from app.agent.schemas import Evidence, Explanation, ParsedQuestion

OBSERVATIONAL = "This is an observational comparison; it does not establish causation."


def _val(metric: str, v: float) -> str:
    return money(v) if metric == "revenue" else num(v)


def template_explanation(ev: Evidence, pq: ParsedQuestion) -> Explanation:
    h, rows, i = ev.headline, ev.supporting_data, ev.analysis_type
    lim = list(ev.limitations)
    if ev.status != "answered":
        return Explanation(answer=f"I couldn't answer this with the available data. {ev.no_answer_reason or ''}".strip(),
                           evidence_bullets=[], analysis="No analysis was run, so no numbers are reported.",
                           limitations=lim or ["The database covers UK online-retail sales Dec 2009 - Dec 2011 plus synthetic campaigns."],
                           follow_ups=[])
    period = ev.periods.get("period") or ev.periods.get("current", "")
    if i == "metric_total":
        m = h["metric"]
        scope = f" ({h['filter']})" if h.get("filter") else ""
        unit = {"orders": " distinct orders", "customers": " distinct customers", "quantity": " units"}.get(m, "")
        ans = f"Total {m}{scope} for {period}: {_val(m, h['total'])}{unit}."
        return Explanation(answer=ans, evidence_bullets=[f"{m}: {_val(m, h['total'])}", f"Period: {period}"],
                           analysis="Single total from one validated query; cancelled invoices are excluded.", limitations=lim, follow_ups=[])
    if i == "revenue_ranking":
        m, dim = h["metric"], h["dimension"]
        key = "product" if dim == "product" else dim
        bullets = [f"{r[key]}: {_val(m, r[m])}" for r in rows[:6]]
        ans = f"{h['leader']} has the highest {m} ({_val(m, h['leader_value'])}) for {period}."
        ana = (f"{h['leader']} leads {h['runner_up']} by {_val(m, h['gap_to_runner_up'])}." if "runner_up" in h else "Only one group was returned.")
        return Explanation(answer=ans, evidence_bullets=bullets, analysis=ana, limitations=lim, follow_ups=[])
    if i == "top_products":
        m = h["metric"]
        bullets = [f"{r['product']}: {_val(m, r[m])} ({pct(r['share_pct'], False)} of total)" for r in rows]
        ans = f"The top product by {m} is {h['top_product']} with {_val(m, h['top_value'])} ({period})."
        ana = f"Together the top {h['n']} products account for {pct(h['top_n_share_pct'], False)} of total {m} ({_val(m, h['total'])}), so revenue is spread across many products."
        return Explanation(answer=ans, evidence_bullets=bullets, analysis=ana, limitations=lim, follow_ups=[])
    if i == "growth_ranking":
        m, dim = h["metric"], h["dimension"]
        key = "product" if dim == "product" else dim
        bullets = [f"{r[key]}: {pct(r['growth_pct'])} ({_val(m, r['previous_value'])} -> {_val(m, r['current_value'])})"
                   + (" [small base, not ranked]" if r["small_base"] else "") for r in rows[:8] if r["growth_pct"] is not None]
        cmp_ = f"{pq.comparison_period.label} to {pq.time_period.label}"
        if "fastest" not in h:
            return Explanation(answer="No group had a large enough base to rank growth.", evidence_bullets=bullets, analysis="",
                               limitations=lim, follow_ups=[])
        ans = f"{h['fastest']} grew fastest: {pct(h['fastest_growth_pct'])} in {m} from {cmp_}."
        ana = f"Overall {m} changed by {pct(h['overall_growth_pct'])} ({_val(m, h['previous_total'])} -> {_val(m, h['current_total'])})."
        if "second" in h:
            ana += f" {h['fastest']} was {num(h['gap_pct_points'], 1)} percentage points ahead of {h['second']} ({pct(h['second_growth_pct'])})."
        return Explanation(answer=ans, evidence_bullets=bullets, analysis=ana, limitations=lim + ["Growth describes what changed, not why."], follow_ups=[])
    if i in ("period_change", "drivers"):
        m = h["metric"]
        scope = f" in {h['filter'].split('=')[1]}" if h.get("filter") else ""
        word = {"increase": "increased", "decrease": "decreased"}.get(h["direction"], "did not change")
        q = ev.question.lower()
        premise = ""
        if h["direction"] == "increase" and re.search(r"\b(decline|declined|drop|dropped|fall|fell|decrease|decreased)\b", q):
            premise = "The premise does not hold: "
        elif h["direction"] == "decrease" and re.search(r"\b(grow|grew|increase|increased|rise|rose)\b", q):
            premise = "The premise does not hold: "
        ans = premise + (f"{m.title()}{scope} {word} by {_val(m, abs(h['change']))} ({pct(h['change_pct'])}) from "
               f"{pq.comparison_period.label} to {pq.time_period.label} ({_val(m, h['previous_total'])} -> {_val(m, h['current_total'])}).")
        first = "category" if i == "drivers" else "region"
        bullets = [f"{r['name']} ({r['dimension']}): {'+' if r['change'] >= 0 else ''}{_val(m, r['change'])}" for r in rows if r["dimension"] == first][:6]
        bullets += [f"{r['name']} (product): {'+' if r['change'] >= 0 else ''}{_val(m, r['change'])}" for r in rows if r["dimension"] == "product"][:6]
        parts = []
        if f"largest_{first}_contributor" in h:
            parts.append(f"The largest {first}-level contribution came from {h[f'largest_{first}_contributor']} ({_val(m, h[f'largest_{first}_change'])}).")
        if "top_positive_product" in h:
            parts.append(f"The biggest product gain was {h['top_positive_product']} (+{_val(m, h['top_positive_product_change'])}).")
        if "top_negative_product" in h:
            parts.append(f"The biggest product decline was {h['top_negative_product']} ({_val(m, h['top_negative_product_change'])}).")
        return Explanation(answer=ans, evidence_bullets=bullets, analysis=" ".join(parts), limitations=lim, follow_ups=[])
    if i == "trend":
        m = h["metric"]
        ans = f"Monthly {m} peaked in {h['peak_month']} ({_val(m, h['peak_value'])}) and was lowest in {h['low_month']} ({_val(m, h['low_value'])})."
        bullets = [f"First full month {h['first_month']}: {_val(m, h['first_value'])}", f"Last full month {h['last_month']}: {_val(m, h['last_value'])}",
                   f"Average month: {_val(m, h['mean_monthly_value'])}", f"Linear slope: {_val(m, h['linear_slope_per_month'])} per month"]
        return Explanation(answer=ans, evidence_bullets=bullets, analysis=f"The series covers {h['months']} complete months and shows strong year-end peaks.",
                           limitations=lim, follow_ups=[])
    if i == "segment_value":
        bullets = [f"{r['segment']} ({r['label']}): {num(r['customers'])} customers, {money(r['revenue'])} ({pct(r['revenue_share_pct'], False)} of revenue)" for r in rows]
        ans = (f"{h['top_segment']} ('{h['top_segment_label']}') generates the most revenue: {money(h['top_segment_revenue'])}, "
               f"{pct(h['top_segment_revenue_share_pct'], False)} of revenue from {pct(h['top_segment_customer_share_pct'], False)} of customers.")
        ana = (f"K-Means chose k = {h['k']} (silhouette {num(h['silhouette'], 3)}) on {num(h['customers_segmented'])} customers. Its median customer "
               f"bought {num(h['top_segment_median_recency_days'])} days before the snapshot, placed {num(h['top_segment_median_frequency'])} orders and spent {money(h['top_segment_median_monetary'])}.")
        return Explanation(answer=ans, evidence_bullets=bullets, analysis=ana, limitations=lim, follow_ups=[])
    if i == "anomaly":
        if not h.get("anomalies_found"):
            return Explanation(answer="No daily revenue value exceeded the anomaly threshold.", evidence_bullets=[], analysis="", limitations=lim, follow_ups=[])
        ans = (f"The largest anomaly was on {h['date']} ({h['weekday']}): revenue {money(h['revenue'])} vs an expected {money(h['expected'])} "
               f"(robust z = {num(h['robust_z'], 2)}).")
        bullets = [f"Deviation: {money(h['deviation'])} {h['direction']} expected", f"Region with the largest deviation: {h.get('top_region')} ({money(h.get('top_region_deviation'))})",
                   f"Top product that day: {h.get('top_product')} ({money(h.get('top_product_revenue'))}, {num(h.get('top_product_units'))} units)",
                   f"Largest single order: invoice {h.get('largest_order_invoice')} ({money(h.get('largest_order_revenue'))}, {pct(h.get('largest_order_share_pct'), False)} of the day)",
                   f"Days flagged in total: {h['anomalies_found']}"]
        ana = ("Most of the deviation comes from a single large order, so this looks like an unusual order rather than a broad change in demand."
               if (h.get("largest_order_share_pct") or 0) > 50 else "The deviation is spread across several orders.")
        if h.get("top_product_cancelled_units"):
            ana += (f" The source data also contains cancellations of {num(h['top_product_cancelled_units'])} units of {h.get('top_product')} by the "
                    "same customer(s) within 30 days, so this spike is likely a data artefact of an order that was later cancelled.")
        return Explanation(answer=ans, evidence_bullets=bullets, analysis=ana, limitations=lim, follow_ups=[])
    if i == "forecast":
        ans = (f"Forecast total revenue for the next {h['horizon_days']} days ({h['forecast_start']} to {h['forecast_end']}): {money(h['forecast_total'])}, "
               f"using {h['best_label']}.")
        bullets = [f"{s['label']}: MAE {money(s['mae'])}, RMSE {money(s['rmse'])}" for s in ev.stats.get("scores", [])]
        ana = (f"Models were scored on a holdout of {h['holdout_start']} to {h['holdout_end']}. "
               + ("The best model beat the seasonal naive baseline." if h["beats_baseline"] else "No model beat the seasonal naive baseline, so the baseline is used."))
        return Explanation(answer=ans, evidence_bullets=bullets, analysis=ana, limitations=lim, follow_ups=[])
    if i in ("campaign_effect", "compare_groups"):
        if i == "campaign_effect":
            higher = h["higher_group"]
            ans = (f"Average daily revenue was higher on {higher}: {money(h['mean_a'])} on campaign days vs {money(h['mean_b'])} on other days "
                   f"({pct(h['relative_difference_pct'])}). {'The difference is statistically significant' if h['significant'] else 'The difference is not statistically significant'} "
                   f"({h['primary_test']}, p = {pval(h['primary_p'])}). {OBSERVATIONAL}")
        else:
            ans = (f"Mean order value: {h['group_a']} {money(h['mean_a'])} vs {h['group_b']} {money(h['mean_b'])}. "
                   f"{'The difference is statistically significant' if h['significant'] else 'The difference is not statistically significant'} "
                   f"({h['primary_test']}, p = {pval(h['primary_p'])}).")
        bullets = [f"n: {num(h['n_a'])} vs {num(h['n_b'])}", f"Medians: {money(h['median_a'])} vs {money(h['median_b'])}",
                   f"Mean difference: {money(h['mean_difference'])} (95% CI {money(h['ci95_low'])} to {money(h['ci95_high'])})",
                   f"Cohen's d: {num(h['cohens_d'], 3)} ({h['effect_size_label']})", f"Mann-Whitney p = {pval(h['mann_whitney_p'])}; Welch p = {pval(h['welch_p'])}"]
        ana = f"The effect size is {h['effect_size_label']}. " + " ".join(ev.stats.get("assumptions", []))
        return Explanation(answer=ans, evidence_bullets=bullets, analysis=ana, limitations=lim + [OBSERVATIONAL], follow_ups=[])
    if i == "association":
        ans = (f"Category mix differs by region in a statistically detectable way (chi-square p = {pval(h['p_value'])}), but the effect is "
               f"{h['effect_size_label']} (Cramer's V = {num(h['cramers_v'], 4)})." if h["significant"] else
               f"No statistically significant association between region and category (p = {pval(h['p_value'])}).")
        bullets = [f"Chi-square = {num(h['chi2'], 2)}, dof = {h['dof']}", f"Order lines: {num(h['n'])}", f"Cramer's V = {num(h['cramers_v'], 4)}"]
        return Explanation(answer=ans, evidence_bullets=bullets, analysis="With about a million lines even tiny differences are significant, so the effect size matters more.",
                           limitations=lim, follow_ups=[])
    if i == "correlation":
        ans = (f"Across {num(h['n'])} products, higher-priced products tend to sell fewer units (Pearson r = {num(h['pearson_r'], 3)} on log scales, "
               f"Spearman rho = {num(h['spearman_rho'], 3)}).") if h["pearson_r"] < 0 else (
               f"Across {num(h['n'])} products, price and units are positively correlated (Pearson r = {num(h['pearson_r'], 3)}).")
        bullets = [f"Pearson r 95% CI: {num(h['pearson_ci95'][0], 3)} to {num(h['pearson_ci95'][1], 3)}", f"Pearson p = {pval(h['pearson_p'])}",
                   f"Spearman p = {pval(h['spearman_p'])}"]
        return Explanation(answer=ans, evidence_bullets=bullets, analysis="This is an association across products, not a causal price effect.",
                           limitations=lim, follow_ups=[])
    return Explanation(answer="Analysis completed.", evidence_bullets=[], analysis="", limitations=lim, follow_ups=[])
