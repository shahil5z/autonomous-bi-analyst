import Link from "next/link";
import type { RunSummary, SavedAnalysis } from "@/lib/types";

export default function Sidebar({ recent, saved, onNew, onOpen, onRemoveSaved, open, onClose }: {
  recent: RunSummary[]; saved: SavedAnalysis[]; onNew: () => void; onOpen: (runId: string) => void;
  onRemoveSaved: (runId: string) => void; open: boolean; onClose: () => void;
}) {
  return (
    <nav aria-label="Sidebar"
         className={`${open ? "flex" : "hidden"} lg:flex flex-col fixed lg:sticky lg:top-14 lg:h-[calc(100vh-3.5rem)] lg:self-start inset-0 z-30 lg:z-auto w-full lg:w-64 shrink-0 bg-gray-50 border-r border-gray-200 p-4 overflow-y-auto`}>
      <div className="flex items-center justify-between lg:hidden mb-3">
        <span className="font-semibold">Menu</span>
        <button onClick={onClose} className="text-sm text-gray-600" aria-label="Close menu">Close</button>
      </div>
      <button onClick={onNew} className="w-full text-sm font-medium bg-gray-900 text-white rounded px-3 py-2 hover:bg-gray-700">
        + New Analysis
      </button>

      <h2 className="mt-6 mb-2 text-[11px] font-semibold tracking-wider text-gray-500 uppercase">Recent Questions</h2>
      {recent.length === 0 ? (
        <p className="text-xs text-gray-500">No questions yet.</p>
      ) : (
        <ul className="space-y-0.5">
          {recent.map((r) => (
            <li key={r.id}>
              <button onClick={() => onOpen(r.id)} className="w-full text-left text-xs text-gray-700 hover:bg-gray-200 rounded px-2 py-1.5 line-clamp-2" title={r.question}>
                {r.question}
              </button>
            </li>
          ))}
        </ul>
      )}

      <h2 className="mt-6 mb-2 text-[11px] font-semibold tracking-wider text-gray-500 uppercase">Saved Analyses</h2>
      {saved.length === 0 ? (
        <p className="text-xs text-gray-500">Use “Save” on an answer to keep it here (stored in this browser).</p>
      ) : (
        <ul className="space-y-0.5">
          {saved.map((s) => (
            <li key={s.run_id} className="flex items-start gap-1">
              <button onClick={() => onOpen(s.run_id)} className="flex-1 text-left text-xs text-gray-700 hover:bg-gray-200 rounded px-2 py-1.5 line-clamp-2">
                {s.question}
              </button>
              <button onClick={() => onRemoveSaved(s.run_id)} className="text-xs text-gray-400 hover:text-gray-800 px-1 py-1.5" aria-label={`Remove saved analysis: ${s.question}`}>×</button>
            </li>
          ))}
        </ul>
      )}

      <h2 className="mt-6 mb-2 text-[11px] font-semibold tracking-wider text-gray-500 uppercase">About</h2>
      <Link href="/methodology" className="block text-xs text-teal-800 hover:underline px-2 py-1">Methodology</Link>

      <div className="mt-auto pt-6">
        <div className="border-t border-gray-200 pt-3 text-[11px] leading-relaxed text-gray-500">
          <p>Built as an AI + Data Science portfolio project by Shahil.</p>
          <p className="mt-1">Data: UCI Online Retail II (CC BY 4.0); campaigns are synthetic.</p>
        </div>
      </div>
    </nav>
  );
}
