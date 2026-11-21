"use client";

import { useMemo } from "react";
import { Gavel, Info } from "lucide-react";
import type { Flow, Verdict } from "@/lib/schema";
import { Guard } from "@/components/Guard";
import { STATUS_STYLE, VerdictBody } from "@/components/legal/VerdictCard";
import { useAgent } from "@/lib/ui/store";

const RANK: Record<Verdict["status"], number> = { violation: 0, questionable: 1, compliant: 2 };

export default function LegalPage() {
  const verdicts = useAgent((s) => s.verdicts);
  const flowById = useAgent((s) => s.flowById);
  const status = useAgent((s) => s.status);
  const select = useAgent((s) => s.select);

  const byApp = useMemo(() => {
    const groups = new Map<string, { v: Verdict; f?: Flow }[]>();
    for (const v of Object.values(verdicts)) {
      const f = flowById[v.flowId];
      const app = f?.app ?? "Unknown app";
      if (!groups.has(app)) groups.set(app, []);
      groups.get(app)!.push({ v, f });
    }
    return [...groups.entries()]
      .map(([app, items]) => ({ app, items: items.sort((a, b) => RANK[a.v.status] - RANK[b.v.status]) }))
      .sort((a, b) => RANK[a.items[0].v.status] - RANK[b.items[0].v.status]);
  }, [verdicts, flowById]);

  const counts = Object.values(verdicts).reduce<Record<string, number>>((acc, v) => ((acc[v.status] = (acc[v.status] ?? 0) + 1), acc), {});

  return (
    <Guard>
      <div className="mx-auto max-w-5xl space-y-4 p-4">
        <div className="flex flex-wrap items-end justify-between gap-3">
          <div>
            <h1 className="text-lg font-semibold">Legal — DPDP Act 2023</h1>
            <p className="text-sm text-muted">Assessments by a local model, restricted to retrieved statute text. Observations, not legal advice.</p>
          </div>
          <div className="flex gap-2 text-xs">
            {(["violation", "questionable", "compliant"] as const).map((s) => (
              <span key={s} className="rounded-full px-2.5 py-1" style={{ color: STATUS_STYLE[s].color, background: `color-mix(in srgb, ${STATUS_STYLE[s].color} 14%, transparent)` }}>
                {counts[s] ?? 0} {STATUS_STYLE[s].label.toLowerCase()}
              </span>
            ))}
          </div>
        </div>

        {status && !status.engines.llm && (
          <p className="flex items-center gap-2 rounded-lg border border-warning/40 bg-warning/10 p-3 text-sm">
            <Info size={16} className="text-warning" aria-hidden /> Legal engine offline — start Ollama with <code className="font-mono text-xs">qwen2.5:7b</code>. Flows and severity keep working.
          </p>
        )}

        {byApp.length === 0 ? (
          <div className="rounded-xl border border-border bg-surface p-10 text-center text-sm text-muted" data-testid="legal-empty">
            <Gavel className="mx-auto mb-3" aria-hidden />
            No verdicts yet. High-severity flows are assessed automatically; open any flow on the Radar and press “Analyze”.
          </div>
        ) : (
          byApp.map(({ app, items }) => (
            <section key={app} aria-label={app} className="space-y-2">
              <h2 className="text-sm font-semibold tracking-wider text-muted uppercase">{app}</h2>
              <div className="grid gap-3 md:grid-cols-2">
                {items.map(({ v, f }) => (
                  <article key={v.flowId} className="rounded-xl border border-border bg-surface p-4" data-testid="verdict-card">
                    <button onClick={() => f && select(f.id)} disabled={!f} className="mb-2 block max-w-full truncate text-left font-mono text-xs text-accent hover:underline disabled:text-muted disabled:no-underline">
                      {f ? `${f.method} ${f.host}` : "flow no longer in memory"}
                    </button>
                    <VerdictBody verdict={v} />
                  </article>
                ))}
              </div>
            </section>
          ))
        )}
      </div>
    </Guard>
  );
}
