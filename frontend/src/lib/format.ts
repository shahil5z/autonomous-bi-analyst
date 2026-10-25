const MONEY_KEYS = /revenue|value|change|total|forecast|actual|expected|deviation|monetary|mean|median|price/i;
const NON_MONEY = /pct|share|growth_pct|_p$|^p$|z$|count|orders|customers|units|quantity|frequency|recency|n_|days|lines|silhouette|cohens|rho|_r$/i;

export function isMoneyKey(key: string): boolean {
  return MONEY_KEYS.test(key) && !NON_MONEY.test(key);
}

export function formatCell(key: string, v: unknown): string {
  if (v === null || v === undefined) return "-";
  if (typeof v === "boolean") return v ? "yes" : "no";
  if (typeof v === "number") {
    if (/pct/.test(key)) return `${v.toFixed(1)}%`;
    if (isMoneyKey(key)) return `£${v.toLocaleString("en-GB", { maximumFractionDigits: 0 })}`;
    if (Number.isInteger(v)) return v.toLocaleString("en-GB");
    return v.toLocaleString("en-GB", { maximumFractionDigits: 3 });
  }
  return String(v);
}

export function compactNumber(v: number): string {
  return new Intl.NumberFormat("en-GB", { notation: "compact", maximumFractionDigits: 1 }).format(v);
}

export function label(key: string): string {
  return key.replace(/_/g, " ").replace(/\bpct\b/, "%");
}
