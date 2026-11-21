"use client";

import { useMemo } from "react";
import { Search, X } from "lucide-react";
import { useAgent } from "@/lib/ui/store";
import { PII_LABEL } from "@/lib/ui/format";

const SELECT = "rounded-md border border-border bg-raised px-2 py-1.5 text-sm";

export function Filters() {
  const flows = useAgent((s) => s.flows);
  const f = useAgent((s) => s.filters);
  const set = useAgent((s) => s.setFilters);
  const reset = useAgent((s) => s.resetFilters);
  const apps = useMemo(() => Array.from(new Set(flows.map((x) => x.app))).sort(), [flows]);
  const active = f.text || f.app || f.company || f.piiType || f.minSeverity || f.onlyPinned;

  return (
    <div className="flex flex-wrap items-center gap-2" role="search">
      <label className="relative">
        <span className="sr-only">Search host, app or company</span>
        <Search size={14} className="pointer-events-none absolute top-1/2 left-2 -translate-y-1/2 text-muted" aria-hidden />
        <input
          value={f.text}
          onChange={(e) => set({ text: e.target.value })}
          placeholder="Search host, app, company"
          className="w-56 rounded-md border border-border bg-raised py-1.5 pr-2 pl-7 text-sm placeholder:text-muted"
        />
      </label>
      <select aria-label="App" className={SELECT} value={f.app ?? ""} onChange={(e) => set({ app: e.target.value || null })}>
        <option value="">All apps</option>
        {apps.map((a) => <option key={a} value={a}>{a}</option>)}
      </select>
      <select aria-label="Data type" className={SELECT} value={f.piiType ?? ""} onChange={(e) => set({ piiType: e.target.value || null })}>
        <option value="">Any data</option>
        {Object.entries(PII_LABEL).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
      </select>
      <select aria-label="Minimum severity" className={SELECT} value={f.minSeverity} onChange={(e) => set({ minSeverity: Number(e.target.value) })}>
        <option value={0}>Any severity</option>
        <option value={35}>Medium+</option>
        <option value={60}>High+</option>
        <option value={80}>Critical</option>
      </select>
      <label className="flex items-center gap-1.5 text-sm text-muted">
        <input type="checkbox" checked={f.onlyPinned} onChange={(e) => set({ onlyPinned: e.target.checked })} className="accent-[var(--accent)]" />
        Pinned only
      </label>
      {f.company && (
        <span className="inline-flex items-center gap-1 rounded-full bg-accent/15 px-2 py-0.5 text-xs text-accent">
          company: {f.company}
        </span>
      )}
      {active && (
        <button onClick={reset} className="inline-flex items-center gap-1 text-xs text-muted hover:text-text">
          <X size={13} aria-hidden /> Clear filters
        </button>
      )}
    </div>
  );
}
