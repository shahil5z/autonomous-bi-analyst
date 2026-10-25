"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import Sidebar from "@/components/Sidebar";
import ResultCard from "@/components/ResultCard";
import TracePanel from "@/components/TracePanel";
import Footer from "@/components/Footer";
import { analyze, ApiError, getHealth, getRun, getSuggestions } from "@/lib/api";
import type { AnalyzeResponse, Health, RunSummary, SavedAnalysis } from "@/lib/types";

const SAVED_KEY = "abi.saved.v2";
const RECENT_KEY = "abi.recent.v1";
const MAX_RECENT = 10;
const FALLBACK_SUGGESTIONS = [
  "Which region has the highest revenue?",
  "Which region grew fastest?",
  "What are the top 5 products?",
  "What is the largest sales anomaly?",
];

function newSessionId() {
  return Math.random().toString(36).slice(2, 12) + Date.now().toString(36);
}

// Recent and saved analyses live in this browser only. Server-side run storage is temporary on serverless
// hosting and is shared between visitors, so it is not listed in the UI.
function readStore<T>(key: string): T[] {
  if (typeof window === "undefined") return [];
  try {
    return JSON.parse(window.localStorage.getItem(key) || "[]");
  } catch {
    return [];
  }
}

function writeStore(key: string, items: unknown[]) {
  try {
    window.localStorage.setItem(key, JSON.stringify(items));
  } catch {
    // storage full or blocked: keep the in-memory list only
  }
}

function toSummary(r: AnalyzeResponse): RunSummary {
  return { id: r.run_id, question: r.question, created_at: "", tools_used: r.evidence.tools_used, final_answer: r.explanation.answer };
}

export default function Home() {
  const session = useRef<string>("");
  const [question, setQuestion] = useState("");
  const [thread, setThread] = useState<AnalyzeResponse[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [recentRuns, setRecentRuns] = useState<AnalyzeResponse[]>([]);
  const [saved, setSaved] = useState<SavedAnalysis[]>([]);
  const [suggestions, setSuggestions] = useState<string[]>(FALLBACK_SUGGESTIONS);
  const [health, setHealth] = useState<Health | null>(null);
  const [useOpenai, setUseOpenai] = useState(true);
  const [showTrace, setShowTrace] = useState(true);
  const [menuOpen, setMenuOpen] = useState(false);
  const bottom = useRef<HTMLDivElement>(null);

  const remember = useCallback((res: AnalyzeResponse) => {
    setRecentRuns((prev) => {
      const next = [res, ...prev.filter((p) => p.run_id !== res.run_id)].slice(0, MAX_RECENT);
      writeStore(RECENT_KEY, next);
      return next;
    });
  }, []);

  useEffect(() => {
    getSuggestions().then((s) => setSuggestions(s.suggestions)).catch(() => undefined);
    getHealth().then(setHealth).catch(() => setHealth(null));
    const t = window.setTimeout(() => {
      setSaved(readStore<SavedAnalysis>(SAVED_KEY));
      setRecentRuns(readStore<AnalyzeResponse>(RECENT_KEY));
    }, 0);
    return () => window.clearTimeout(t);
  }, []);

  useEffect(() => {
    bottom.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [thread.length, loading]);

  const ask = useCallback(async (q: string) => {
    const text = q.trim();
    if (!text || loading) return;
    if (!session.current) session.current = newSessionId();
    setLoading(true);
    setError(null);
    setQuestion("");
    try {
      const res = await analyze(text, session.current, useOpenai);
      session.current = res.session_id;
      setThread((t) => [...t, res]);
      remember(res);
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Unexpected error.");
      setQuestion(text);
    } finally {
      setLoading(false);
    }
  }, [loading, useOpenai, remember]);

  const newAnalysis = () => {
    session.current = newSessionId();
    setThread([]);
    setError(null);
    setQuestion("");
    setMenuOpen(false);
  };

  const openRun = async (id: string) => {
    setMenuOpen(false);
    setError(null);
    const local = recentRuns.find((r) => r.run_id === id) || saved.find((s) => s.run_id === id)?.response;
    if (local) {
      session.current = local.session_id;
      setThread([local]);
      return;
    }
    try {
      const run = await getRun(id);
      session.current = run.session_id;
      setThread([run]);
    } catch (e) {
      setError(e instanceof ApiError && e.code !== "not_found" ? e.message
        : "That analysis is no longer stored. Server-side storage is temporary on this deployment; ask the question again.");
    }
  };

  const persist = (items: SavedAnalysis[]) => {
    setSaved(items);
    writeStore(SAVED_KEY, items);
  };
  const save = (r: AnalyzeResponse) => {
    if (saved.some((s) => s.run_id === r.run_id)) return;
    persist([{ run_id: r.run_id, question: r.question, saved_at: new Date().toISOString(), response: r }, ...saved].slice(0, 20));
  };

  const latest = thread.length ? thread[thread.length - 1] : null;
  const aiAvailable = health?.openai_configured ?? false;

  return (
    <div className="flex flex-col min-h-screen">
      <header className="flex items-center justify-between gap-3 border-b border-gray-200 bg-white px-4 py-2.5">
        <div className="flex items-center gap-3">
          <button className="lg:hidden text-sm border border-gray-300 rounded px-2 py-1" onClick={() => setMenuOpen(true)} aria-label="Open menu">Menu</button>
          <div>
            <h1 className="text-sm font-semibold text-gray-900">ABI Analyst</h1>
            <p className="text-[11px] text-gray-500 hidden sm:block">Ask questions about two years of online-retail sales (Dec 2009 – Dec 2011)</p>
          </div>
        </div>
        <div className="flex items-center gap-3 text-xs">
          <label className={`flex items-center gap-1.5 ${aiAvailable ? "text-gray-700" : "text-gray-400"}`}
                 title={aiAvailable ? "Use OpenAI to parse unclear questions and write the explanation" : "No OpenAI key configured on the backend: template explanations only"}>
            <input type="checkbox" checked={useOpenai && aiAvailable} disabled={!aiAvailable} onChange={(e) => setUseOpenai(e.target.checked)} />
            AI explanations
          </label>
          {!showTrace && (
            <button onClick={() => setShowTrace(true)} className="border border-gray-300 rounded px-2 py-1 hover:bg-gray-50">Show trace</button>
          )}
        </div>
      </header>

      <div className="flex flex-1 min-h-0 flex-col lg:flex-row">
        <Sidebar recent={recentRuns.map(toSummary)} saved={saved} onNew={newAnalysis} onOpen={openRun}
                 onRemoveSaved={(id) => persist(saved.filter((s) => s.run_id !== id))} open={menuOpen} onClose={() => setMenuOpen(false)} />

        <main className="flex-1 min-w-0 px-4 py-6 lg:px-8">
          <div className="max-w-3xl mx-auto">
            {health && !health.database.ok && (
              <p role="alert" className="mb-4 text-sm text-amber-900 bg-amber-50 border border-amber-200 rounded p-3">
                The backend is running but the database is missing. Run <code>python scripts/run_pipeline.py</code>.
              </p>
            )}

            {thread.length === 0 && !loading && (
              <section aria-label="Getting started" className="mb-6">
                <h2 className="text-xl font-semibold text-gray-900">What would you like to know?</h2>
                <p className="mt-1 text-sm text-gray-600">
                  Questions are turned into a validated analysis plan. SQL and Python compute every number; the language model only explains
                  the results, and its wording is checked against them.
                </p>
                <div className="mt-4 grid sm:grid-cols-2 gap-2">
                  {suggestions.map((s) => (
                    <button key={s} onClick={() => ask(s)} className="text-left text-sm bg-white border border-gray-200 rounded px-3 py-2 hover:border-gray-400">
                      {s}
                    </button>
                  ))}
                </div>
              </section>
            )}

            <div className="space-y-5">
              {thread.map((r) => (
                <ResultCard key={r.run_id} result={r} onFollowUp={ask} onSave={() => save(r)} busy={loading}
                            saved={saved.some((s) => s.run_id === r.run_id)} />
              ))}
            </div>

            {loading && (
              <div role="status" className="mt-5 bg-white border border-gray-200 rounded-md p-5 text-sm text-gray-600">
                <span className="inline-block h-2 w-2 rounded-full bg-teal-700 animate-pulse mr-2" aria-hidden />
                Analysing: planning, running queries and checking the results…
              </div>
            )}
            {error && (
              <p role="alert" className="mt-5 text-sm text-red-800 bg-red-50 border border-red-200 rounded p-3">{error}</p>
            )}
            <div ref={bottom} />

            <form onSubmit={(e) => { e.preventDefault(); ask(question); }}
                  className="sticky bottom-0 mt-6 pt-3 pb-4 bg-[var(--background)]">
              <label htmlFor="question" className="sr-only">Ask a question about the sales data</label>
              <div className="flex gap-2">
                <input id="question" value={question} onChange={(e) => setQuestion(e.target.value)} maxLength={500}
                       placeholder={thread.length ? "Ask a follow-up, e.g. “What about Germany?”" : "e.g. Which region grew fastest?"}
                       className="flex-1 min-w-0 bg-white border border-gray-300 rounded px-3 py-2 text-sm focus:border-teal-700" />
                <button type="submit" disabled={loading || !question.trim()}
                        className="bg-teal-800 text-white text-sm font-medium rounded px-4 py-2 hover:bg-teal-900 disabled:opacity-50">
                  Ask
                </button>
              </div>
            </form>
          </div>
        </main>

        {showTrace && <TracePanel result={latest} loading={loading} onClose={() => setShowTrace(false)} />}
      </div>
      <Footer />
    </div>
  );
}
