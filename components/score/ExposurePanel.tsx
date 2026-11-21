"use client";

import { ShieldCheck, TrendingDown } from "lucide-react";
import { useAgent } from "@/lib/ui/store";
import { sendCommand } from "@/lib/ui/socket";
import { CATEGORY_LABEL, CATEGORY_MAX } from "@/lib/ui/format";

const R = 80;
const CIRC = Math.PI * R; // semicircle length

function gaugeColor(total: number) {
  if (total >= 700) return "var(--danger)";
  if (total >= 400) return "var(--warning)";
  if (total >= 150) return "var(--accent)";
  return "var(--success)";
}

export function Gauge({ total, size = 220 }: { total: number; size?: number }) {
  const pct = Math.max(0, Math.min(1, total / 1000));
  const color = gaugeColor(total);
  return (
    <svg viewBox="0 0 200 118" width={size} role="img" aria-label={`Exposure score ${Math.round(total)} out of 1000`} data-testid="gauge">
      <path d={`M 20 100 A ${R} ${R} 0 0 1 180 100`} fill="none" stroke="var(--raised)" strokeWidth="16" strokeLinecap="round" />
      <path
        d={`M 20 100 A ${R} ${R} 0 0 1 180 100`}
        fill="none"
        stroke={color}
        strokeWidth="16"
        strokeLinecap="round"
        strokeDasharray={`${CIRC * pct} ${CIRC}`}
        style={{ transition: "stroke-dasharray 600ms ease, stroke 600ms ease" }}
      />
      <text x="100" y="86" textAnchor="middle" fill="var(--text)" fontSize="36" fontWeight="700" fontFamily="var(--font-jetbrains)">
        {Math.round(total)}
      </text>
      <text x="100" y="108" textAnchor="middle" fill="var(--muted)" fontSize="10">
        / 1000 exposure
      </text>
    </svg>
  );
}

export function ExposurePanel({ compact = false }: { compact?: boolean }) {
  const score = useAgent((s) => s.score);
  const remediation = useAgent((s) => s.remediation);
  const blocklist = useAgent((s) => s.blocklist);
  const conn = useAgent((s) => s.conn);
  const recheckInsight = useAgent((s) => s.insights["recheck"]);
  const scoreBefore = (recheckInsight?.data as { scoreBefore?: number } | undefined)?.scoreBefore;

  if (!score) {
    return (
      <section className="rounded-xl border border-border bg-surface p-4 text-sm text-muted" data-testid="exposure-empty">
        <h2 className="mb-2 font-semibold text-text">Exposure Score</h2>
        {conn === "open" ? "Waiting for the first scored flows…" : "No score yet — the agent is not connected."}
      </section>
    );
  }

  const recheck = blocklist?.recheck;
  return (
    <section className="space-y-4 rounded-xl border border-border bg-surface p-4" aria-label="Exposure score">
      <div className="flex items-center justify-between">
        <h2 className="font-semibold">Exposure Score</h2>
        {blocklist?.applied && (
          <span className="inline-flex items-center gap-1 rounded-full bg-success/15 px-2 py-0.5 text-xs text-success">
            <ShieldCheck size={12} aria-hidden /> Patronus active
          </span>
        )}
      </div>
      <div className="flex justify-center">
        <Gauge total={score.total} size={compact ? 190 : 230} />
      </div>
      {recheck && (
        <div className="rounded-lg border border-success/40 bg-success/10 p-3 text-sm" data-testid="recheck">
          <p className="flex items-center gap-2 font-medium text-success">
            <TrendingDown size={16} aria-hidden /> Leaks {recheck.baseline} → {recheck.current}
          </p>
          {scoreBefore !== undefined && (
            <p className="mt-0.5 font-mono text-xs text-text">
              Exposure {Math.round(scoreBefore)} → {Math.round(score.total)}
            </p>
          )}
          <p className="mt-0.5 text-xs text-muted">
            {recheck.delta <= 0 ? `${-recheck.delta} fewer leaks since the blocklist was applied.` : `${recheck.delta} more leaks than baseline.`}
          </p>
        </div>
      )}
      <ul className="space-y-2">
        {score.categories.map((c) => {
          const max = CATEGORY_MAX[c.name] ?? 250;
          return (
            <li key={c.name} className="text-xs">
              <div className="mb-1 flex justify-between">
                <span className="text-muted">{CATEGORY_LABEL[c.name] ?? c.name}</span>
                <span className="font-mono tabular-nums">
                  {Math.round(c.value)}<span className="text-muted">/{max}</span>
                </span>
              </div>
              <div className="h-1.5 rounded-full bg-raised">
                <div className="h-full rounded-full bg-hero transition-[width] duration-500" style={{ width: `${Math.min(100, (c.value / max) * 100)}%` }} />
              </div>
            </li>
          );
        })}
      </ul>
      {!compact && <Remediation items={remediation} />}
      <button
        disabled={conn !== "open" || blocklist?.applied}
        onClick={() => sendCommand({ type: "blocklist", action: "apply" })}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-hero px-4 py-2 font-medium text-white enabled:hover:brightness-110 disabled:opacity-40"
        data-testid="apply-blocklist"
      >
        <ShieldCheck size={16} aria-hidden /> {blocklist?.applied ? "Blocklist applied" : "Apply Blocklist (cast Patronus)"}
      </button>
    </section>
  );
}

export function Remediation({ items }: { items: { target: string; kind: "host" | "company"; reduction: number }[] }) {
  if (!items.length) return <p className="text-xs text-muted">No remediation needed yet.</p>;
  const top = items[0].reduction || 1;
  return (
    <div>
      <h3 className="mb-2 text-xs font-semibold tracking-wider text-muted uppercase">Block first (largest score drop)</h3>
      <ol className="space-y-1.5" data-testid="remediation">
        {items.map((r, i) => (
          <li key={r.target} className="flex items-center gap-2 text-sm">
            <span className="w-4 text-right font-mono text-xs text-muted">{i + 1}</span>
            <span className="min-w-0 flex-1">
              <span className={`block truncate ${r.kind === "host" ? "font-mono text-xs" : ""}`}>{r.target}</span>
              <span className="block h-1 rounded bg-danger/70" style={{ width: `${(r.reduction / top) * 100}%` }} />
            </span>
            <span className="font-mono text-xs text-success tabular-nums">−{r.reduction}</span>
          </li>
        ))}
      </ol>
    </div>
  );
}
