import type { AnalyzeResponse, Health, RunSummary } from "./types";

export const API_BASE = (process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000").replace(/\/$/, "");

export class ApiError extends Error {
  constructor(message: string, public code: string) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  let res: Response;
  try {
    res = await fetch(`${API_BASE}${path}`, { ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) } });
  } catch {
    throw new ApiError("Cannot reach the analysis API. Is the backend running on " + API_BASE + "?", "network_error");
  }
  const body = await res.json().catch(() => null);
  if (!res.ok) {
    const err = body?.error;
    throw new ApiError(err?.message || `Request failed (${res.status}).`, err?.code || "http_error");
  }
  return body as T;
}

export const analyze = (question: string, sessionId: string, useOpenai: boolean) =>
  request<AnalyzeResponse>("/api/analyze", {
    method: "POST",
    body: JSON.stringify({ question, session_id: sessionId, use_openai: useOpenai }),
  });

export const getRuns = () => request<{ runs: RunSummary[] }>("/api/runs?limit=15");
export const getRun = (id: string) => request<AnalyzeResponse & { created_at: string }>(`/api/runs/${encodeURIComponent(id)}`);
export const getSuggestions = () => request<{ suggestions: string[] }>("/api/suggestions");
export const getHealth = () => request<Health>("/health");
