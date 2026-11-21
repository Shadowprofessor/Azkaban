"use client";

import { useEffect, useState } from "react";
import { Eye, Gavel, Loader2, Lock, Unlock, X } from "lucide-react";
import type { PiiHit } from "@/lib/schema";
import { useAgent } from "@/lib/ui/store";
import { sendCommand } from "@/lib/ui/socket";
import { fmtBytes, PII_LABEL } from "@/lib/ui/format";
import { SeverityChip } from "./FlowList";
import { VerdictBody } from "@/components/legal/VerdictCard";

function PiiRow({ hit }: { hit: PiiHit }) {
  const [shown, setShown] = useState(false);
  return (
    <li className="flex items-center gap-2 rounded-md bg-raised px-2 py-1.5 text-sm">
      <span className="w-20 shrink-0 text-xs text-hero">{PII_LABEL[hit.type]}</span>
      <button
        onClick={() => setShown((v) => !v)}
        className="min-w-0 flex-1 truncate text-left font-mono text-xs"
        aria-label={shown ? "Hide redacted value" : "Reveal redacted value"}
        title="Values are redacted by the agent; this only un-blurs the redacted form."
      >
        {shown ? hit.redacted : <span className="inline-flex items-center gap-1 text-muted"><Eye size={12} aria-hidden /> click to reveal (redacted)</span>}
      </button>
      <span className="font-mono text-[11px] text-muted tabular-nums">{Math.round(hit.confidence * 100)}%</span>
    </li>
  );
}

function Field({ k, v, mono }: { k: string; v: React.ReactNode; mono?: boolean }) {
  return (
    <>
      <dt className="text-muted">{k}</dt>
      <dd className={`min-w-0 break-all ${mono ? "font-mono text-xs" : ""}`}>{v}</dd>
    </>
  );
}

export function FlowDrawer() {
  const id = useAgent((s) => s.selectedFlowId);
  const flow = useAgent((s) => (id ? s.flowById[id] : undefined));
  const verdict = useAgent((s) => (id ? s.verdicts[id] : undefined));
  const pending = useAgent((s) => (id ? s.pendingAnalyze[id] : undefined));
  const conn = useAgent((s) => s.conn);
  const llm = useAgent((s) => s.status?.engines.llm);
  const select = useAgent((s) => s.select);
  const markAnalyze = useAgent((s) => s.markAnalyze);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && select(null);
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [select]);

  if (!id || !flow) return null;
  const waiting = !!pending && !verdict;

  return (
    <div className="fixed inset-0 z-40" role="dialog" aria-modal="true" aria-label={`Flow details: ${flow.app} to ${flow.host}`}>
      <button className="absolute inset-0 bg-black/50" aria-label="Close details" onClick={() => select(null)} />
      <aside className="azk-enter absolute top-0 right-0 flex h-full w-full max-w-md flex-col overflow-y-auto border-l border-border bg-surface shadow-2xl" data-testid="drawer">
        <header className="flex items-start gap-3 border-b border-border p-4">
          <div className="min-w-0 flex-1">
            <p className="text-sm text-muted">{flow.app}</p>
            <h2 className="truncate font-mono text-sm font-semibold">{flow.host}</h2>
          </div>
          <SeverityChip value={flow.severity} />
          <button onClick={() => select(null)} aria-label="Close" className="text-muted hover:text-text">
            <X size={18} />
          </button>
        </header>

        <div className="space-y-5 p-4">
          <div className="flex flex-wrap gap-2 text-xs">
            {flow.decrypted ? (
              <span className="inline-flex items-center gap-1 rounded-full bg-success/15 px-2 py-0.5 text-success"><Unlock size={12} aria-hidden /> Decrypted</span>
            ) : (
              <span className="inline-flex items-center gap-1 rounded-full bg-warning/15 px-2 py-0.5 text-warning"><Lock size={12} aria-hidden /> Pinned — metadata only</span>
            )}
            {flow.tracker && <span className="rounded-full bg-danger/15 px-2 py-0.5 text-danger">Dementor: {flow.tracker.name} · {flow.tracker.category}</span>}
          </div>

          <dl className="grid grid-cols-[6rem_1fr] gap-x-3 gap-y-1.5 text-sm">
            <Field k="Method" v={flow.method} mono />
            <Field k="Path" v={flow.path || "—"} mono />
            <Field k="IP" v={flow.ip || "—"} mono />
            <Field k="Country" v={flow.country} mono />
            <Field k="Company" v={flow.company || "—"} />
            <Field k="Bytes" v={fmtBytes(flow.bytes)} />
            <Field k="Time" v={new Date(flow.ts).toLocaleString()} />
          </dl>

          <section>
            <h3 className="mb-2 text-xs font-semibold tracking-wider text-muted uppercase">Personal data ({flow.pii.length})</h3>
            {flow.pii.length ? (
              <ul className="space-y-1.5">{flow.pii.map((h, i) => <PiiRow key={i} hit={h} />)}</ul>
            ) : (
              <p className="text-sm text-muted">{flow.decrypted ? "No personal data detected in this request." : "Payload not visible: the app pins its certificate."}</p>
            )}
          </section>

          <section>
            <h3 className="mb-2 text-xs font-semibold tracking-wider text-muted uppercase">Consent signal (IAB TCF)</h3>
            {flow.tcf ? (
              <p className="text-sm">
                {flow.tcf.purposes.length} purposes · {flow.tcf.vendors.length} vendors
                <span className="mt-1 block font-mono text-xs text-muted">purposes: {flow.tcf.purposes.join(", ") || "none"}</span>
              </p>
            ) : (
              <p className="text-sm text-muted">No consent string observed in this request.</p>
            )}
          </section>

          <section>
            <h3 className="mb-2 text-xs font-semibold tracking-wider text-muted uppercase">DPDP verdict</h3>
            {verdict ? (
              <VerdictBody verdict={verdict} />
            ) : (
              <button
                disabled={conn !== "open" || !llm || !!waiting}
                onClick={() => {
                  if (sendCommand({ type: "analyze", flowId: flow.id })) markAnalyze(flow.id);
                }}
                className="inline-flex items-center gap-2 rounded-lg border border-border bg-raised px-3 py-1.5 text-sm hover:bg-border disabled:opacity-40"
                data-testid="analyze"
              >
                {waiting ? <Loader2 size={15} className="animate-spin" aria-hidden /> : <Gavel size={15} aria-hidden />}
                {waiting ? "Consulting the law… (local LLM)" : llm === false ? "Legal engine offline" : "Analyze under DPDP Act"}
              </button>
            )}
          </section>
        </div>
      </aside>
    </div>
  );
}
