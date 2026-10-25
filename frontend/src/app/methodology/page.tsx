import Link from "next/link";
import Footer from "@/components/Footer";

export const metadata = { title: "Methodology · ABI Analyst" };

const SECTIONS: { id: string; title: string; body: React.ReactNode }[] = [
  {
    id: "architecture", title: "Architecture",
    body: (
      <>
        <p>A Next.js frontend talks to a FastAPI backend. The backend owns a read-only DuckDB database built from the UCI Online Retail II dataset, a small set of analysis tools written in Python, and an optional OpenAI client. Analysis runs are stored in SQLite so they can be reopened.</p>
        <pre className="text-xs bg-gray-50 border border-gray-200 rounded p-3 overflow-x-auto">{`Browser (Next.js)
   │  POST /api/analyze
   ▼
FastAPI ── Question Analyzer ── Planner ── Router ── Tools ── Validator ── Evidence ── Explanation
                 │ (optional LLM)                       │                                  │ (optional LLM,
                 ▼                                      ▼                                  ▼  grounding check)
            OpenAI API                     DuckDB (read-only)                         OpenAI API`}</pre>
      </>
    ),
  },
  {
    id: "workflow", title: "Agent workflow",
    body: (
      <ol className="list-decimal pl-5 space-y-1">
        <li><b>Understand</b>: a deterministic parser recognises common question shapes (rankings, growth, change between periods, forecasts, anomalies, segments, campaigns, statistical comparisons). Only when it is not confident is the question sent to OpenAI, which must return a fixed JSON schema. The result is validated against the known intents, metrics, dimensions and entity names.</li>
        <li><b>Plan</b>: the validated question becomes an explicit plan of tool calls. The plan is code, not free text.</li>
        <li><b>Execute</b>: the router calls only registered tools. There is no shell, file-system or arbitrary-code tool.</li>
        <li><b>Validate</b>: results are checked (non-empty, finite numbers, group totals reconcile with an independent total, periods are inside the data range, sample sizes are adequate for the test used).</li>
        <li><b>Evidence</b>: a structured evidence object holds the headline numbers, supporting rows, SQL, periods and limitations.</li>
        <li><b>Explain</b>: OpenAI (or a deterministic template) writes the answer from the evidence only.</li>
      </ol>
    ),
  },
  {
    id: "sql", title: "SQL generation and safety",
    body: (
      <>
        <p>The language model never writes SQL. Queries are compiled from a typed specification (metric, group-by, filters, period, limit) with bound parameters. Every query, including the fixed ones inside tools, passes one validation function before it runs:</p>
        <ul className="list-disc pl-5 space-y-0.5">
          <li>single statement, parsed with sqlglot; only <code>SELECT</code> (and CTEs) allowed;</li>
          <li>keyword blocklist (INSERT, UPDATE, DELETE, DROP, ATTACH, COPY, PRAGMA, INSTALL, LOAD, …) checked after string literals are removed;</li>
          <li>tables and columns must be in an allowlist; no schema-qualified names or table functions (e.g. <code>read_csv</code>);</li>
          <li>a <code>LIMIT</code> is added or capped;</li>
          <li>the DuckDB connection is opened read-only with external access disabled, and long queries are interrupted after a timeout.</li>
        </ul>
      </>
    ),
  },
  {
    id: "tools", title: "Tool calling",
    body: <p>Tools: SQL query, aggregation (top-N, growth, change decomposition), statistics, time series, forecasting, segmentation, anomaly detection and chart specification. Each returns a typed result (rows, summary numbers, SQL used, method name, limitations). The frontend shows the high-level trace of these steps, not internal reasoning.</p>,
  },
  {
    id: "validation", title: "Validation and grounding",
    body: <p>After an explanation is written, every number in it is extracted and must match a number in the evidence (allowing for rounding, percentages and £k/£m formatting). Numbers that appear only inside data strings, such as product descriptions, do not count as evidence. Causal words such as “caused” or “drove” are rejected for observational analyses (campaigns, correlations). If any check fails, the deterministic template is used instead and the reason is shown.</p>,
  },
  {
    id: "stats", title: "Statistical methods",
    body: (
      <ul className="list-disc pl-5 space-y-0.5">
        <li>Two-group comparisons: Shapiro–Wilk and Levene checks choose between Student&apos;s t, Welch&apos;s t and Mann–Whitney U; 95% confidence interval for the mean difference and Cohen&apos;s d are reported.</li>
        <li>Category mix vs region: chi-square test of independence on order-line counts (sparse groups dropped) with Cramér&apos;s V.</li>
        <li>Price vs units: Pearson on log values with a Fisher confidence interval, plus Spearman.</li>
        <li>Campaigns: daily revenue on (synthetic) campaign days vs other trading days. These results are observational and say nothing about causation.</li>
      </ul>
    ),
  },
  {
    id: "forecasting", title: "Forecasting",
    body: <p>Daily revenue (non-trading days filled with zero, last partial day excluded) is forecast with three simple models: seasonal naive (same weekday last week), the mean of the same weekday over the previous four weeks, and a ridge regression on trend and calendar features. The last <i>h</i> days are held out, each model is scored with MAE and RMSE, and the best one is used. If nothing beats the seasonal naive baseline, the baseline is used and that is stated. Horizons above 90 days are refused. Only point forecasts are produced.</p>,
  },
  {
    id: "anomalies", title: "Anomaly detection",
    body: <p>Each trading day is compared with the median of the previous 28 trading days using a robust z-score (median absolute deviation, threshold 3.5), cross-checked with an IQR rule. The largest anomaly is drilled down by region, product and order, and checked against cancellations: the largest spike in this dataset is one very large order that was cancelled the same day.</p>,
  },
  {
    id: "segmentation", title: "Customer segmentation",
    body: <p>Recency, frequency and monetary value per customer, log-transformed and standardised, clustered with K-Means for k = 2–6. The k with the best silhouette score is used and segments are labelled by comparing their medians to the overall medians. About a fifth of sales lines have no customer ID and are excluded from segmentation.</p>,
  },
  {
    id: "visualisation", title: "Visualisation",
    body: <p>The backend returns a declarative chart specification only when a chart helps (bar for rankings and contributions, area for trends, line for forecasts and anomalies, box summary for group comparisons, heatmap for category mix, log–log scatter for price vs units). The table behind every chart is available under “View Data”.</p>,
  },
  {
    id: "openai", title: "How OpenAI is used",
    body: <p>At most two calls per question: one to parse an unclear question into a fixed schema, and one to write the explanation from the evidence object. The API key stays on the backend. The app works without a key: the deterministic parser and template explanations are used and labelled as such.</p>,
  },
  {
    id: "why", title: "Why the LLM never computes numbers",
    body: <p>Language models are good at wording and poor at arithmetic over large tables, and their mistakes look plausible. Keeping all computation in SQL and Python makes every number reproducible from the SQL shown in the interface, and the grounding check makes the model&apos;s role narrow and testable.</p>,
  },
  {
    id: "security", title: "Security",
    body: <p>Read-only database, SQL allowlists, no tools that touch the file system or run code, input length limits, structured errors without stack traces, and CORS restricted to configured origins. Text from the data (for example product descriptions) is treated as data: the test fixture plants an “ignore previous instructions” product description and the tests check it cannot change the answer.</p>,
  },
  {
    id: "limitations", title: "Limitations",
    body: (
      <ul className="list-disc pl-5 space-y-0.5">
        <li>One public dataset of a single UK online retailer (2009–2011); no costs, margins or marketing spend.</li>
        <li>Campaigns, product categories and regions are derived or synthetic, not part of the source data.</li>
        <li>The deterministic parser covers a fixed set of question types; unusual phrasing depends on the optional LLM parser.</li>
        <li>Conversation memory is in-process and short-lived.</li>
        <li>Statistical results are observational; forecasts are point estimates from about two years of history.</li>
      </ul>
    ),
  },
];

export default function Methodology() {
  return (
    <div className="flex flex-col min-h-screen">
      <header className="border-b border-gray-200 bg-white px-4 py-2.5 flex items-center justify-between">
        <div className="flex items-center gap-3">
          {/* eslint-disable-next-line @next/next/no-img-element */}
          <img src="/abi-icon-128.webp" alt="" width={32} height={32} className="h-8 w-8 rounded-md shrink-0" />
          <h1 className="text-sm font-semibold">ABI Analyst · Methodology</h1>
        </div>
        <Link href="/" className="text-xs text-teal-800 hover:underline">← Back to the analyst</Link>
      </header>
      <div className="flex-1 max-w-3xl mx-auto px-4 py-8">
        <nav aria-label="On this page" className="mb-8 text-xs flex flex-wrap gap-x-3 gap-y-1">
          {SECTIONS.map((s) => <a key={s.id} href={`#${s.id}`} className="text-teal-800 hover:underline">{s.title}</a>)}
        </nav>
        {SECTIONS.map((s) => (
          <section key={s.id} id={s.id} className="mb-8 scroll-mt-6">
            <h2 className="text-lg font-semibold text-gray-900 mb-2">{s.title}</h2>
            <div className="text-sm text-gray-700 leading-relaxed space-y-2">{s.body}</div>
          </section>
        ))}
      </div>
      <Footer />
    </div>
  );
}
