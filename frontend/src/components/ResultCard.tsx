"use client";

import { useState } from "react";
import type { AnalyzeResponse } from "@/lib/types";
import ChartView from "./ChartView";
import DataTable from "./DataTable";

type Panel = "sql" | "data" | "method" | null;

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="mt-5">
      <h3 className="text-[11px] font-semibold tracking-wider text-gray-500 uppercase mb-1.5">{title}</h3>
      {children}
    </section>
  );
}

export default function ResultCard({ result, onFollowUp, onSave, saved, busy }: {
  result: AnalyzeResponse; onFollowUp: (q: string) => void; onSave: () => void; saved: boolean; busy: boolean;
}) {
  const [panel, setPanel] = useState<Panel>(null);
  const { explanation: ex, evidence: ev } = result;
  const answered = ev.status === "answered";
  const toggle = (p: Panel) => setPanel((cur) => (cur === p ? null : p));
  const tabs: { id: Exclude<Panel, null>; label: string; show: boolean }[] = [
    { id: "sql", label: "View SQL", show: ev.sql.length > 0 },
    { id: "data", label: "View Data", show: ev.supporting_data.length > 0 },
    { id: "method", label: "View Method", show: true },
  ];

  return (
    <article className="bg-white border border-gray-200 rounded-md p-5" aria-labelledby={`q-${result.run_id}`}>
      <div className="flex items-start justify-between gap-3">
        <h2 id={`q-${result.run_id}`} className="text-base font-semibold text-gray-900">
          {result.parsed.is_follow_up && <span className="mr-2 text-xs font-medium text-teal-800 bg-teal-50 border border-teal-200 rounded px-1.5 py-0.5 align-middle">follow-up</span>}
          {result.question}
        </h2>
        {answered && (
          <button onClick={onSave} disabled={saved} className="shrink-0 text-xs border border-gray-300 rounded px-2 py-1 hover:bg-gray-50 disabled:text-gray-400">
            {saved ? "Saved" : "Save"}
          </button>
        )}
      </div>

      <Section title="Answer">
        <p className={`text-[15px] leading-relaxed ${answered ? "text-gray-900" : "text-amber-900"}`}>{ex.answer}</p>
        <p className="mt-1 text-[11px] text-gray-500">
          {result.explanation_source === "openai"
            ? "Written by OpenAI from the computed evidence; every number passed the grounding check."
            : "Deterministic template explanation (OpenAI not used or its draft was rejected)."}
          {result.explanation_note && result.explanation_source === "template" && result.explanation_note.startsWith("OpenAI explanation rejected") ? ` ${result.explanation_note}` : ""}
        </p>
      </Section>

      {ex.evidence_bullets.length > 0 && (
        <Section title="Evidence">
          <ul className="list-disc pl-5 space-y-0.5 text-sm text-gray-800">
            {ex.evidence_bullets.map((b, i) => <li key={i}>{b}</li>)}
          </ul>
        </Section>
      )}

      {ev.chart && (
        <div className="mt-5 border border-gray-100 rounded p-3">
          <ChartView spec={ev.chart} />
        </div>
      )}

      {answered && (
        <Section title="Analysis">
          <p className="text-sm text-gray-800 leading-relaxed">{ex.analysis}</p>
        </Section>
      )}

      {ex.limitations.length > 0 && (
        <Section title="Limitations">
          <ul className="list-disc pl-5 space-y-0.5 text-sm text-gray-600">
            {ex.limitations.map((l, i) => <li key={i}>{l}</li>)}
          </ul>
        </Section>
      )}

      <div className="mt-5 flex flex-wrap gap-2" role="group" aria-label="Details">
        {tabs.filter((t) => t.show).map((t) => (
          <button key={t.id} onClick={() => toggle(t.id)} aria-expanded={panel === t.id} aria-controls={`panel-${result.run_id}`}
                  className={`text-xs rounded px-2.5 py-1 border ${panel === t.id ? "bg-gray-900 text-white border-gray-900" : "border-gray-300 text-gray-700 hover:bg-gray-50"}`}>
            {t.label}
          </button>
        ))}
      </div>

      {panel && (
        <div id={`panel-${result.run_id}`} className="mt-3">
          {panel === "sql" && (
            <div className="space-y-3">
              {ev.sql.map((s, i) => (
                <div key={i}>
                  <p className="text-xs text-gray-600 mb-1">{i + 1}. {s.purpose} <span className="text-gray-400">({s.row_count} rows)</span></p>
                  <pre className="text-[11px] leading-snug bg-gray-50 border border-gray-200 rounded p-2 overflow-x-auto whitespace-pre-wrap">{s.display_sql}</pre>
                </div>
              ))}
              <p className="text-[11px] text-gray-500">Queries are built from a validated plan with bound parameters (shown inlined for readability) and pass the SQL safety layer before running on a read-only connection.</p>
            </div>
          )}
          {panel === "data" && <DataTable rows={ev.supporting_data} columns={ev.columns} caption={`Data for: ${result.question}`} />}
          {panel === "method" && (
            <div className="text-sm text-gray-700 space-y-2">
              <p><span className="font-medium">Plan:</span> {result.plan.summary}</p>
              <ol className="list-decimal pl-5 space-y-0.5">{result.plan.human_steps.map((s, i) => <li key={i}>{s}</li>)}</ol>
              <p><span className="font-medium">Method:</span> {ev.method.replace(/_/g, " ")}{ev.tools_used.length ? ` · tools: ${ev.tools_used.join(", ")}` : ""}</p>
              {ev.validation.length > 0 && (
                <ul className="text-xs space-y-0.5">
                  {ev.validation.map((v, i) => (
                    <li key={i}><span className={v.passed ? "text-teal-800" : "text-amber-800"}>{v.passed ? "✓" : "✗"}</span> {v.name}{v.detail ? ` (${v.detail})` : ""}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      )}

      <Section title="Data lineage">
        <ol className="flex flex-wrap items-center gap-1 text-[11px] text-gray-600">
          {result.lineage.map((l, i) => (
            <li key={i} className="flex items-center gap-1">
              <span className="border border-gray-200 rounded px-1.5 py-0.5 bg-gray-50" title={l.detail}>
                <span className="font-medium text-gray-800">{l.stage}</span>: {l.detail}
              </span>
              {i < result.lineage.length - 1 && <span aria-hidden className="text-gray-400">→</span>}
            </li>
          ))}
        </ol>
      </Section>

      {result.follow_ups.length > 0 && (
        <Section title="Follow-up questions">
          <div className="flex flex-wrap gap-2">
            {result.follow_ups.map((f) => (
              <button key={f} onClick={() => onFollowUp(f)} disabled={busy}
                      className="text-xs text-teal-900 border border-teal-200 bg-teal-50 hover:bg-teal-100 rounded-full px-3 py-1 disabled:opacity-50">
                {f}
              </button>
            ))}
          </div>
        </Section>
      )}
    </article>
  );
}
