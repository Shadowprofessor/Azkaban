"use client";

import { ExternalLink } from "lucide-react";
import type { Verdict } from "@/lib/schema";

export const STATUS_STYLE: Record<Verdict["status"], { color: string; label: string }> = {
  violation: { color: "var(--danger)", label: "Violation" },
  questionable: { color: "var(--warning)", label: "Questionable" },
  compliant: { color: "var(--success)", label: "Compliant" },
};

export function StatusBadge({ status }: { status: Verdict["status"] }) {
  const { color, label } = STATUS_STYLE[status];
  return (
    <span className="rounded-full px-2 py-0.5 text-xs font-semibold" style={{ color, background: `color-mix(in srgb, ${color} 16%, transparent)` }}>
      {label}
    </span>
  );
}

export function VerdictBody({ verdict }: { verdict: Verdict }) {
  return (
    <div className="space-y-2">
      <StatusBadge status={verdict.status} />
      <p className="text-sm leading-relaxed">{verdict.reasoning}</p>
      {verdict.citations.length ? (
        <ul className="flex flex-wrap gap-1.5">
          {verdict.citations.map((c) => (
            <li key={c.section}>
              <a
                href={c.url}
                target="_blank"
                rel="noreferrer noopener"
                className="inline-flex items-center gap-1 rounded-md border border-accent/40 bg-accent/10 px-2 py-0.5 text-xs text-accent hover:bg-accent/20"
                title={c.source}
              >
                {c.section} <span className="text-muted">· {c.source.replace("Digital Personal Data Protection Act, 2023", "DPDP Act 2023")}</span>
                <ExternalLink size={11} aria-hidden />
              </a>
            </li>
          ))}
        </ul>
      ) : (
        <p className="text-xs text-muted italic">Not covered by indexed law — no citation available.</p>
      )}
    </div>
  );
}
