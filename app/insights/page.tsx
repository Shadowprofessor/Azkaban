"use client";

import { useMemo, useState } from "react";
import {
  Bird, Fingerprint, Gauge as GaugeIcon, Hash, Link2, Moon, Network, RefreshCcw, ShieldAlert, Sparkles, Waves,
} from "lucide-react";
import type { InsightMsg } from "@/lib/live/protocol";
import { Guard } from "@/components/Guard";
import { useAgent } from "@/lib/ui/store";
import { fmtBytes } from "@/lib/ui/format";

type Kind = InsightMsg["kind"] | "beacon_anomaly" | "unknown_tracker";

const KIND: Record<string, { label: string; icon: typeof Moon }> = {
  honeytoken: { label: "Canary", icon: Bird },
  hashed_pii: { label: "Hashed identifiers", icon: Hash },
  cross_app: { label: "Cross-app tracking", icon: Link2 },
  idle_beacons: { label: "Idle beacons", icon: Moon },
  bandwidth: { label: "Bandwidth", icon: Waves },
  dns_bypass: { label: "Proxy bypass", icon: Network },
  recheck: { label: "Recheck", icon: RefreshCcw },
  unknown_tracker: { label: "Unlisted tracker", icon: Fingerprint },
  beacon_anomaly: { label: "Beacon anomaly", icon: GaugeIcon },
};
const LEVEL_COLOR = { critical: "var(--danger)", warn: "var(--warning)", info: "var(--accent)" } as const;
const ORDER: Record<string, number> = { critical: 0, warn: 1, info: 2 };

function Bars({ data, fmt = (n: number) => String(n) }: { data: Record<string, number>; fmt?: (n: number) => string }) {
  const entries = Object.entries(data).slice(0, 6);
  const max = Math.max(1, ...entries.map(([, v]) => v));
  return (
    <ul className="mt-3 space-y-1.5">
      {entries.map(([k, v]) => (
        <li key={k} className="grid grid-cols-[minmax(0,9rem)_1fr_4.5rem] items-center gap-2 text-xs">
          <span className="truncate text-muted">{k}</span>
          <span className="h-1.5 rounded-full bg-raised"><span className="block h-full rounded-full bg-hero" style={{ width: `${(v / max) * 100}%` }} /></span>
          <span className="text-right font-mono tabular-nums">{fmt(v)}</span>
        </li>
      ))}
    </ul>
  );
}

function Detail({ i }: { i: InsightMsg }) {
  const d = i.data as Record<string, unknown>;
  if (i.kind === "idle_beacons" && d.byApp) return <Bars data={d.byApp as Record<string, number>} />;
  if (i.kind === "bandwidth" && d.byCompany) return <Bars data={d.byCompany as Record<string, number>} fmt={fmtBytes} />;
  if (i.kind === "dns_bypass" && d.byApp)
    return <Bars data={Object.fromEntries(Object.entries(d.byApp as Record<string, unknown[]>).map(([k, v]) => [k, v.length]))} />;
  if (i.kind === "recheck")
    return (
      <p className="mt-2 font-mono text-sm">
        leaks {String(d.baseline)} → {String(d.current)} · score {Math.round(Number(d.scoreBefore))} → {Math.round(Number(d.scoreAfter))}
      </p>
    );
  const chips = ["app", "company", "host", "pii", "algo", "field", "via", "apps"].filter((k) => d[k] !== undefined);
  if (!chips.length) return null;
  return (
    <div className="mt-2 flex flex-wrap gap-1.5">
      {chips.map((k) => (
        <span key={k} className="rounded bg-raised px-1.5 py-0.5 font-mono text-[11px]">
          <span className="text-muted">{k}:</span> {String(d[k])}
        </span>
      ))}
    </div>
  );
}

function InsightCard({ i }: { i: InsightMsg }) {
  const meta = KIND[i.kind] ?? { label: i.kind, icon: Sparkles };
  const Icon = meta.icon;
  const color = LEVEL_COLOR[i.level];
  return (
    <article className="azk-enter rounded-xl border bg-surface p-4" style={{ borderColor: `color-mix(in srgb, ${color} 45%, var(--border))` }} data-testid={`insight-${i.kind}`}>
      <div className="flex items-start gap-3">
        <span className="grid h-8 w-8 shrink-0 place-items-center rounded-lg" style={{ background: `color-mix(in srgb, ${color} 15%, transparent)`, color }}>
          <Icon size={16} aria-hidden />
        </span>
        <div className="min-w-0 flex-1">
          <p className="text-[11px] tracking-wider text-muted uppercase">{meta.label}</p>
          <h3 className="font-medium">{i.title}</h3>
          <p className="mt-1 text-sm text-muted">{i.detail}</p>
          <Detail i={i} />
        </div>
      </div>
    </article>
  );
}

export default function InsightsPage() {
  const insights = useAgent((s) => s.insights);
  const order = useAgent((s) => s.insightOrder);
  const conn = useAgent((s) => s.conn);
  const [kind, setKind] = useState<Kind | "all">("all");

  const list = useMemo(
    () =>
      order
        .map((k) => insights[k])
        .filter((i): i is InsightMsg => !!i && (kind === "all" || i.kind === kind))
        .sort((a, b) => ORDER[a.level] - ORDER[b.level]),
    [order, insights, kind],
  );
  const kinds = useMemo(() => Array.from(new Set(order.map((k) => insights[k]?.kind).filter(Boolean))) as Kind[], [order, insights]);
  const canary = list.filter((i) => i.kind === "honeytoken");
  const rest = list.filter((i) => i.kind !== "honeytoken");

  return (
    <Guard>
      <div className="mx-auto max-w-5xl space-y-4 p-4">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <h1 className="text-lg font-semibold">Insights</h1>
          <div className="flex flex-wrap gap-1" role="tablist" aria-label="Filter insights">
            {(["all", ...kinds] as (Kind | "all")[]).map((k) => (
              <button
                key={k}
                role="tab"
                aria-selected={kind === k}
                onClick={() => setKind(k)}
                className={`rounded-full px-3 py-1 text-xs ${kind === k ? "bg-accent text-bg" : "bg-raised text-muted hover:text-text"}`}
              >
                {k === "all" ? "All" : KIND[k]?.label ?? k}
              </button>
            ))}
          </div>
        </div>

        {canary.map((i) => (
          <div key={i.key} className="rounded-2xl border-2 border-danger bg-danger/10 p-5" data-testid="canary-hero">
            <p className="flex items-center gap-2 text-sm font-semibold tracking-wider text-danger uppercase">
              <ShieldAlert size={18} aria-hidden /> Canary tripped — proof of exfiltration
            </p>
            <h2 className="mt-1 text-xl font-semibold">{i.title.replace(/^CANARY TRIPPED:s*/i, "")}</h2>
            <p className="mt-1 text-sm text-muted">{i.detail}</p>
            <Detail i={i} />
          </div>
        ))}

        {list.length === 0 ? (
          <p className="rounded-xl border border-border bg-surface p-8 text-center text-sm text-muted" data-testid="insights-empty">
            {conn === "open" ? "No insights yet. They appear as patterns emerge across flows." : "Agent offline — insights appear once it connects."}
          </p>
        ) : (
          <div className="grid gap-3 md:grid-cols-2">{rest.map((i) => <InsightCard key={i.key} i={i} />)}</div>
        )}
      </div>
    </Guard>
  );
}
