"use client";

import { useMemo, useRef } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import { Lock, Radar } from "lucide-react";
import type { Flow } from "@/lib/schema";
import { applyFilters, useAgent } from "@/lib/ui/store";
import { fmtTime, PII_LABEL, severityTone } from "@/lib/ui/format";

export function SeverityChip({ value }: { value: number }) {
  const { color, label } = severityTone(value);
  return (
    <span
      className="inline-flex min-w-[3.25rem] items-center justify-center gap-1 rounded-md px-1.5 py-0.5 font-mono text-xs font-semibold tabular-nums"
      style={{ color, background: `color-mix(in srgb, ${color} 16%, transparent)` }}
      title={`${label} severity`}
    >
      {value}
    </span>
  );
}

export function PiiBadges({ flow, max = 4 }: { flow: Flow; max?: number }) {
  const types = Array.from(new Set(flow.pii.map((p) => p.type)));
  return (
    <span className="flex flex-wrap gap-1">
      {types.slice(0, max).map((t) => (
        <span key={t} className="rounded border border-hero/40 bg-hero/10 px-1.5 text-[11px] text-hero">
          {PII_LABEL[t]}
        </span>
      ))}
      {types.length > max && <span className="text-[11px] text-muted">+{types.length - max}</span>}
    </span>
  );
}

function Row({ flow, onOpen, selected }: { flow: Flow; onOpen: () => void; selected: boolean }) {
  const pinned = !flow.decrypted;
  return (
    <button
      onClick={onOpen}
      data-testid="flow-row"
      data-pinned={pinned || undefined}
      className={`grid h-full w-full grid-cols-[4.5rem_minmax(0,9rem)_minmax(0,1fr)_3.5rem] items-center gap-3 border-b border-border/60 px-3 text-left text-sm md:grid-cols-[4.5rem_minmax(0,9rem)_minmax(0,1.4fr)_minmax(0,1fr)_3rem_minmax(0,9rem)_3.5rem] ${
        selected ? "bg-raised" : "hover:bg-raised/60"
      } ${pinned ? "bg-[repeating-linear-gradient(135deg,transparent_0_8px,rgba(148,163,184,0.06)_8px_16px)]" : ""}`}
    >
      <span className="font-mono text-xs text-muted tabular-nums">{fmtTime(flow.ts)}</span>
      <span className="truncate font-medium">{flow.app}</span>
      <span className="flex min-w-0 items-center gap-1.5">
        {pinned && <Lock size={13} className="shrink-0 text-warning" aria-label="Pinned: metadata only" />}
        <span className={`truncate font-mono text-xs ${pinned ? "text-muted italic" : ""}`}>{flow.host}</span>
      </span>
      <span className="hidden truncate text-xs text-muted md:block">
        {flow.tracker ? <span className="text-danger/90">{flow.company || flow.tracker.name}</span> : flow.company || "—"}
      </span>
      <span className="hidden text-xs md:block" title={flow.country}>
        <span className="font-mono text-muted">{flow.country}</span>
      </span>
      <span className="hidden md:block">
        {pinned ? <span className="text-[11px] text-warning">pinned · no payload</span> : <PiiBadges flow={flow} max={3} />}
      </span>
      <span className="justify-self-end">
        <SeverityChip value={flow.severity} />
      </span>
    </button>
  );
}

export function FlowList() {
  const flows = useAgent((s) => s.flows);
  const filters = useAgent((s) => s.filters);
  const selected = useAgent((s) => s.selectedFlowId);
  const select = useAgent((s) => s.select);
  const conn = useAgent((s) => s.conn);
  const visible = useMemo(() => applyFilters(flows, filters), [flows, filters]);
  const parentRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line react-hooks/incompatible-library -- TanStack Virtual is the requested virtualiser
  const v = useVirtualizer({ count: visible.length, getScrollElement: () => parentRef.current, estimateSize: () => 44, overscan: 12 });

  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden rounded-xl border border-border bg-surface">
      <div className="hidden grid-cols-[4.5rem_minmax(0,9rem)_minmax(0,1.4fr)_minmax(0,1fr)_3rem_minmax(0,9rem)_3.5rem] gap-3 border-b border-border px-3 py-2 text-[11px] tracking-wider text-muted uppercase md:grid">
        <span>Time</span><span>App</span><span>Host</span><span>Company</span><span>Geo</span><span>Data</span><span className="justify-self-end">Sev</span>
      </div>
      {visible.length === 0 ? (
        <div className="grid flex-1 place-items-center p-10 text-center text-sm text-muted" data-testid="radar-empty">
          <div>
            <Radar className={`mx-auto mb-3 ${conn === "open" ? "azk-pulse text-accent" : ""}`} size={32} aria-hidden />
            {flows.length
              ? "No flows match these filters."
              : conn === "open"
                ? "Listening… flows appear here as your device talks to the internet."
                : conn === "connecting"
                  ? "Connecting to your local agent…"
                  : "Agent offline. Start it to see The Trace."}
          </div>
        </div>
      ) : (
        <div ref={parentRef} className="min-h-0 flex-1 overflow-auto" data-testid="flow-list">
          <div style={{ height: v.getTotalSize(), position: "relative" }}>
            {v.getVirtualItems().map((item) => {
              const f = visible[item.index];
              return (
                <div key={f.id} style={{ position: "absolute", top: 0, left: 0, right: 0, height: item.size, transform: `translateY(${item.start}px)` }}>
                  <Row flow={f} selected={selected === f.id} onOpen={() => select(f.id)} />
                </div>
              );
            })}
          </div>
        </div>
      )}
      <div className="border-t border-border px-3 py-1.5 text-[11px] text-muted" data-testid="flow-count">
        {visible.length} of {flows.length} flows{flows.length >= 2000 ? " (showing latest 2000)" : ""}
      </div>
    </div>
  );
}
