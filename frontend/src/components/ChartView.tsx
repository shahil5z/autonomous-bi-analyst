"use client";

import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Legend, Line, LineChart, ResponsiveContainer,
  Scatter, ScatterChart, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import type { ChartSpec } from "@/lib/types";
import { compactNumber, formatCell, label } from "@/lib/format";

const INK = "#1f2937";
const ACCENT = "#0f766e";
const NEG = "#b45309";
const SERIES = [ACCENT, "#6b7280", NEG];

const axisProps = { tick: { fontSize: 11, fill: "#4b5563" }, stroke: "#d1d5db" };

function tickLabel(v: unknown): string {
  const s = String(v);
  return s.length > 18 ? s.slice(0, 17) + "…" : s;
}

function Heatmap({ spec }: { spec: ChartSpec }) {
  const rows = spec.data;
  const rowKey = spec.y[0];
  const colKey = spec.x;
  const rowNames = [...new Set(rows.map((r) => String(r[rowKey])))];
  const colNames = [...new Set(rows.map((r) => String(r[colKey])))];
  const cell = new Map(rows.map((r) => [`${r[rowKey]}|${r[colKey]}`, Number(r.share_pct) || 0]));
  const max = Math.max(...cell.values(), 1);
  return (
    <div className="overflow-x-auto">
      <table className="text-xs border-collapse">
        <thead>
          <tr>
            <th scope="col" className="p-1 text-left font-medium text-gray-600">{label(rowKey)}</th>
            {colNames.map((c) => (
              <th key={c} scope="col" className="p-1 font-medium text-gray-600 align-bottom">{c}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rowNames.map((rn) => (
            <tr key={rn}>
              <th scope="row" className="p-1 pr-3 whitespace-nowrap text-left font-normal text-gray-700">{rn}</th>
              {colNames.map((c) => {
                const v = cell.get(`${rn}|${c}`) ?? 0;
                return (
                  <td key={c} className="p-1 text-center tabular-nums"
                      style={{ backgroundColor: `rgba(15,118,110,${(v / max) * 0.75 + 0.05})`, color: v / max > 0.55 ? "white" : INK }}>
                    {v.toFixed(1)}
                  </td>
                );
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function BoxSummary({ spec }: { spec: ChartSpec }) {
  const rows = spec.data as Record<string, number | string>[];
  const max = Math.max(...rows.map((r) => Number(r.max) || 0), 1);
  const pos = (v: unknown) => `${((Number(v) || 0) / max) * 100}%`;
  return (
    <div className="space-y-5 py-2">
      {rows.map((r) => (
        <div key={String(r[spec.x])}>
          <div className="text-xs text-gray-700 mb-1">{String(r[spec.x])}</div>
          <div className="relative h-6" role="img"
               aria-label={`${r[spec.x]}: median ${formatCell("median", r.median)}, interquartile range ${formatCell("q1", r.q1)} to ${formatCell("q3", r.q3)}`}>
            <div className="absolute top-3 h-px bg-gray-400" style={{ left: pos(r.min), width: `calc(${pos(r.max)} - ${pos(r.min)})` }} />
            <div className="absolute top-0 h-6 border border-teal-800 bg-teal-50" style={{ left: pos(r.q1), width: `calc(${pos(r.q3)} - ${pos(r.q1)})` }} />
            <div className="absolute top-0 h-6 w-0.5 bg-teal-800" style={{ left: pos(r.median) }} />
          </div>
          <div className="flex justify-between text-[11px] text-gray-500 tabular-nums">
            <span>min {formatCell("min_value", r.min)}</span>
            <span>median {formatCell("median", r.median)}</span>
            <span>max (1.5 IQR) {formatCell("max_value", r.max)}</span>
          </div>
        </div>
      ))}
    </div>
  );
}

export default function ChartView({ spec }: { spec: ChartSpec }) {
  const data = spec.data;
  const money = (v: number) => (spec.y_label === "%" ? `${v}%` : compactNumber(v));
  const tooltipFmt = (value: unknown, name: unknown) => [formatCell(String(name), value), label(String(name))] as [string, string];

  let chart: React.ReactNode = null;
  if (spec.type === "heatmap") chart = <Heatmap spec={spec} />;
  else if (spec.type === "box") chart = <BoxSummary spec={spec} />;
  else if (spec.type === "bar") {
    const key = spec.y[0];
    const horizontal = data.length > 6 || data.some((d) => String(d[spec.x]).length > 14);
    chart = (
      <ResponsiveContainer width="100%" height={horizontal ? Math.max(220, data.length * 28) : 260}>
        <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" horizontal={!horizontal} vertical={horizontal} />
          {horizontal ? (
            <>
              <XAxis type="number" tickFormatter={money} {...axisProps} />
              <YAxis type="category" dataKey={spec.x} width={170} tickFormatter={tickLabel} {...axisProps} />
            </>
          ) : (
            <>
              <XAxis dataKey={spec.x} tickFormatter={tickLabel} {...axisProps} />
              <YAxis tickFormatter={money} width={56} {...axisProps} />
            </>
          )}
          <Tooltip formatter={tooltipFmt} />
          <Bar dataKey={key} isAnimationActive={false}>
            {data.map((d, i) => (
              <Cell key={i} fill={Number(d[key]) < 0 ? NEG : ACCENT} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    );
  } else if (spec.type === "area") {
    chart = (
      <ResponsiveContainer width="100%" height={260}>
        <AreaChart data={data} margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey={spec.x} {...axisProps} minTickGap={24} />
          <YAxis tickFormatter={money} width={56} {...axisProps} />
          <Tooltip formatter={tooltipFmt} />
          <Area dataKey={spec.y[0]} stroke={ACCENT} fill="#ccfbf1" isAnimationActive={false} />
        </AreaChart>
      </ResponsiveContainer>
    );
  } else if (spec.type === "line") {
    const flagged = data.some((d) => "in_campaign" in d);
    chart = (
      <ResponsiveContainer width="100%" height={280}>
        <LineChart data={data} margin={{ left: 8, right: 16, top: 8, bottom: 8 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis dataKey={spec.x} {...axisProps} minTickGap={32} />
          <YAxis tickFormatter={money} width={56} {...axisProps} />
          <Tooltip formatter={tooltipFmt} />
          {spec.y.length > 1 && <Legend wrapperStyle={{ fontSize: 12 }} />}
          {spec.y.map((k, i) => (
            <Line key={k} dataKey={k} stroke={k.endsWith("_80") ? "#9ca3af" : SERIES[i % SERIES.length]} dot={false} strokeWidth={1.5}
                  strokeDasharray={k === "expected" || k === "forecast" ? "4 3" : k.endsWith("_80") ? "2 3" : undefined} isAnimationActive={false} connectNulls={false} />
          ))}
          {flagged && (
            <Line dataKey={(d: Record<string, unknown>) => (d.in_campaign ? d.revenue : null)} name="campaign day" stroke="none"
                  dot={{ r: 2.5, fill: NEG, stroke: NEG }} isAnimationActive={false} />
          )}
        </LineChart>
      </ResponsiveContainer>
    );
  } else if (spec.type === "scatter") {
    chart = (
      <ResponsiveContainer width="100%" height={300}>
        <ScatterChart margin={{ left: 8, right: 16, top: 8, bottom: 16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
          <XAxis type="number" dataKey={spec.x} name={label(spec.x)} scale="log" domain={["auto", "auto"]} tickFormatter={(v) => `£${v}`} {...axisProps} />
          <YAxis type="number" dataKey={spec.y[0]} name={label(spec.y[0])} scale="log" domain={["auto", "auto"]} tickFormatter={compactNumber} width={56} {...axisProps} />
          <ZAxis range={[14, 14]} />
          <Tooltip formatter={tooltipFmt} />
          <Scatter data={data} fill={ACCENT} fillOpacity={0.45} isAnimationActive={false} />
        </ScatterChart>
      </ResponsiveContainer>
    );
  }

  return (
    <figure aria-label={spec.title}>
      <figcaption className="text-sm font-medium text-gray-800 mb-2">{spec.title}</figcaption>
      {chart}
      {spec.note && <p className="text-xs text-gray-500 mt-1">{spec.note}</p>}
      <span className="sr-only">Chart data is also available under View Data.</span>
    </figure>
  );
}
