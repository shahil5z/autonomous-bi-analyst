import type { AnalyzeResponse } from "@/lib/types";

export default function TracePanel({ result, loading, onClose }: { result: AnalyzeResponse | null; loading: boolean; onClose: () => void }) {
  return (
    <aside aria-label="Analysis trace" className="w-full lg:w-72 shrink-0 border-t lg:border-t-0 lg:border-l border-gray-200 bg-white p-4 text-sm">
      <div className="flex items-center justify-between mb-3">
        <h2 className="font-semibold text-gray-900">Analysis Trace</h2>
        <button onClick={onClose} className="text-xs text-gray-500 hover:text-gray-900" aria-label="Hide analysis trace">Hide</button>
      </div>
      {loading && <p className="text-gray-500 text-xs" role="status">Running analysis…</p>}
      {!loading && !result && <p className="text-gray-500 text-xs">Ask a question to see how it was answered.</p>}
      {!loading && result && (
        <>
          <ol className="space-y-2">
            {result.trace.map((t, i) => (
              <li key={i} className="flex gap-2">
                <span aria-hidden className={t.status === "done" ? "text-teal-700" : t.status === "failed" ? "text-amber-700" : "text-gray-400"}>
                  {t.status === "done" ? "✓" : t.status === "failed" ? "✗" : "–"}
                </span>
                <div>
                  <p className="text-gray-800">{t.label}<span className="sr-only"> ({t.status})</span></p>
                  {t.detail && <p className="text-[11px] text-gray-500">{t.detail}</p>}
                </div>
              </li>
            ))}
          </ol>
          <dl className="mt-4 pt-3 border-t border-gray-100 text-[11px] text-gray-500 grid grid-cols-2 gap-y-1">
            <dt>Question parser</dt><dd className="text-gray-700">{result.parsed.parser}</dd>
            <dt>Explanation</dt><dd className="text-gray-700">{result.explanation_source}</dd>
            <dt>OpenAI calls</dt><dd className="text-gray-700">{result.openai_calls}</dd>
            <dt>Time</dt><dd className="text-gray-700">{(result.duration_ms / 1000).toFixed(1)} s</dd>
          </dl>
          <p className="mt-3 text-[11px] text-gray-400">High-level steps only. Numbers come from SQL and Python tools, never from the language model.</p>
        </>
      )}
    </aside>
  );
}
