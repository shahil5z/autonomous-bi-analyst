export type Period = { label: string; start: string; end: string };
export type Filter = { dimension: string; values: string[] };

export type ParsedQuestion = {
  intent: string;
  metrics: string[];
  dimensions: string[];
  time_period: Period | null;
  comparison_period: Period | null;
  filters: Filter[];
  is_follow_up: boolean;
  parser: "deterministic" | "openai";
  parser_note?: string | null;
  unsupported_reason?: string | null;
};

export type SQLRecord = { purpose: string; sql: string; params: unknown[]; display_sql: string; row_count: number };

export type ChartSpec = {
  type: "line" | "bar" | "area" | "scatter" | "histogram" | "box" | "heatmap";
  title: string;
  x: string;
  y: string[];
  data: Record<string, unknown>[];
  x_label?: string | null;
  y_label?: string | null;
  note?: string | null;
};

export type ValidationCheck = { name: string; passed: boolean; detail: string };

export type Evidence = {
  question: string;
  status: "answered" | "no_answer" | "error";
  analysis_type: string;
  method: string;
  headline: Record<string, unknown>;
  supporting_data: Record<string, unknown>[];
  columns: string[];
  stats: Record<string, unknown>;
  sql: SQLRecord[];
  periods: Record<string, string>;
  tables: string[];
  chart: ChartSpec | null;
  limitations: string[];
  validation: ValidationCheck[];
  no_answer_reason: string | null;
  tools_used: string[];
};

export type Explanation = {
  answer: string;
  evidence_bullets: string[];
  analysis: string;
  limitations: string[];
  follow_ups: string[];
};

export type TraceStep = { label: string; status: "done" | "skipped" | "failed"; detail?: string | null };
export type LineageStep = { stage: string; detail: string };

export type AnalyzeResponse = {
  run_id: string;
  session_id: string;
  question: string;
  parsed: ParsedQuestion;
  plan: { intent: string; summary: string; human_steps: string[]; statistical_test: boolean; chart: boolean };
  evidence: Evidence;
  explanation: Explanation;
  explanation_source: "openai" | "template";
  explanation_note: string | null;
  grounding: { passed: boolean; unmatched_numbers: string[]; causal_language: string[] };
  follow_ups: string[];
  trace: TraceStep[];
  lineage: LineageStep[];
  openai_calls: number;
  duration_ms: number;
};

export type RunSummary = { id: string; question: string; created_at: string; tools_used: string[] | string; final_answer: string };

export type Health = {
  status: string;
  database: { ok: boolean; date_range?: [string, string] };
  openai_configured: boolean;
  model: string;
};

export type SavedAnalysis = { run_id: string; question: string; saved_at: string };
