import { formatCell, label } from "@/lib/format";

export default function DataTable({ rows, columns, caption, max = 25 }: {
  rows: Record<string, unknown>[]; columns: string[]; caption: string; max?: number;
}) {
  const cols = columns.length ? columns : Object.keys(rows[0] || {});
  const shown = rows.slice(0, max);
  return (
    <div className="overflow-x-auto border border-gray-200 rounded">
      <table className="w-full text-xs">
        <caption className="sr-only">{caption}</caption>
        <thead className="bg-gray-50 text-gray-600">
          <tr>
            {cols.map((c) => (
              <th key={c} scope="col" className="px-2 py-1.5 text-left font-medium whitespace-nowrap">{label(c)}</th>
            ))}
          </tr>
        </thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i} className="border-t border-gray-100">
              {cols.map((c) => (
                <td key={c} className={`px-2 py-1 whitespace-nowrap ${typeof r[c] === "number" ? "text-right tabular-nums" : ""}`}>
                  {formatCell(c, r[c])}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
      {rows.length > max && <p className="px-2 py-1 text-[11px] text-gray-500 border-t">Showing {max} of {rows.length} rows.</p>}
    </div>
  );
}
