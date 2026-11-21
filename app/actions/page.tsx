"use client";

import { useState } from "react";
import { ListChecks, ShieldCheck, TrendingDown, Wand2 } from "lucide-react";
import { Guard } from "@/components/Guard";
import { CopyButton } from "@/components/CopyButton";
import { Gauge, Remediation } from "@/components/score/ExposurePanel";
import { useAgent } from "@/lib/ui/store";
import { sendCommand } from "@/lib/ui/socket";

const FORMATS = [
  { key: "hosts", label: "hosts file", hint: "Append to /etc/hosts or C:\\Windows\\System32\\drivers\\etc\\hosts" },
  { key: "pihole", label: "Pi-hole", hint: "Group Management → Domains → add as exact deny" },
  { key: "nextdns", label: "NextDNS", hint: "Denylist → paste one domain per line" },
  { key: "pf", label: "pf (macOS/BSD)", hint: "Add to /etc/pf.conf, then pfctl -f /etc/pf.conf" },
] as const;

export default function ActionsPage() {
  const score = useAgent((s) => s.score);
  const remediation = useAgent((s) => s.remediation);
  const blocklist = useAgent((s) => s.blocklist);
  const conn = useAgent((s) => s.conn);
  const recheckInsight = useAgent((s) => s.insights["recheck"]);
  const [fmt, setFmt] = useState<(typeof FORMATS)[number]["key"]>("hosts");
  const before = (recheckInsight?.data as { scoreBefore?: number } | undefined)?.scoreBefore;
  const off = conn !== "open";

  return (
    <Guard>
      <div className="mx-auto max-w-5xl space-y-4 p-4">
        <div>
          <h1 className="text-lg font-semibold">Patronus — action report</h1>
          <p className="text-sm text-muted">Block the Dementors that cost you the most, then prove the fix worked.</p>
        </div>

        <div className="grid gap-4 md:grid-cols-[1fr_1.3fr]">
          <section className="space-y-3 rounded-xl border border-border bg-surface p-4">
            <h2 className="flex items-center gap-2 font-semibold"><ListChecks size={16} aria-hidden /> Ranked remediation</h2>
            {score ? <Remediation items={remediation} /> : <p className="text-sm text-muted">No score yet.</p>}
          </section>

          <section className="space-y-3 rounded-xl border border-border bg-surface p-4" data-testid="recheck-panel">
            <h2 className="flex items-center gap-2 font-semibold"><TrendingDown size={16} aria-hidden /> Apply & recheck</h2>
            {blocklist?.recheck ? (
              <div className="flex flex-wrap items-center gap-6">
                {before !== undefined && score && (
                  <div className="flex items-center gap-2">
                    <Gauge total={before} size={130} />
                    <span className="text-2xl text-muted">→</span>
                    <Gauge total={score.total} size={130} />
                  </div>
                )}
                <div>
                  <p className="font-mono text-3xl font-bold text-success">{blocklist.recheck.baseline} → {blocklist.recheck.current}</p>
                  <p className="text-sm text-muted">leaks before vs after (Δ {blocklist.recheck.delta})</p>
                </div>
              </div>
            ) : (
              <p className="text-sm text-muted">
                Applying stores the current leak count as a baseline, enforces the blocklist inside the proxy and starts counting again.
                In replay mode the session restarts so the comparison is like-for-like.
              </p>
            )}
            <div className="flex flex-wrap gap-2">
              <button disabled={off} onClick={() => sendCommand({ type: "blocklist", action: "generate" })} className="inline-flex items-center gap-2 rounded-lg border border-border bg-raised px-3 py-1.5 text-sm hover:bg-border disabled:opacity-40">
                <Wand2 size={15} aria-hidden /> Generate rules
              </button>
              <button disabled={off || blocklist?.applied} onClick={() => sendCommand({ type: "blocklist", action: "apply" })} className="inline-flex items-center gap-2 rounded-lg bg-hero px-3 py-1.5 text-sm font-medium text-white hover:brightness-110 disabled:opacity-40" data-testid="apply-blocklist-actions">
                <ShieldCheck size={15} aria-hidden /> {blocklist?.applied ? "Applied" : "Apply & recheck"}
              </button>
            </div>
          </section>
        </div>

        <section className="rounded-xl border border-border bg-surface p-4">
          <div className="mb-3 flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-semibold">Blocklist ({blocklist?.hosts.length ?? 0} hosts)</h2>
            <div role="tablist" aria-label="Rule format" className="flex flex-wrap gap-1">
              {FORMATS.map((f) => (
                <button key={f.key} role="tab" aria-selected={fmt === f.key} onClick={() => setFmt(f.key)} className={`rounded-full px-3 py-1 text-xs ${fmt === f.key ? "bg-accent text-bg" : "bg-raised text-muted hover:text-text"}`}>
                  {f.label}
                </button>
              ))}
            </div>
          </div>
          {blocklist ? (
            <>
              <div className="mb-2 flex items-center justify-between gap-2">
                <p className="text-xs text-muted">{FORMATS.find((f) => f.key === fmt)!.hint}</p>
                <CopyButton text={blocklist.formats[fmt]} label={`Copy ${FORMATS.find((f) => f.key === fmt)!.label}`} />
              </div>
              <pre className="max-h-72 overflow-auto rounded-lg bg-bg p-3 font-mono text-xs leading-relaxed" data-testid="blocklist-format">{blocklist.formats[fmt]}</pre>
            </>
          ) : (
            <p className="text-sm text-muted">Press “Generate rules” to build a blocklist from the flagged destinations.</p>
          )}
        </section>
      </div>
    </Guard>
  );
}
