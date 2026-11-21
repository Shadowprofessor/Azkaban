"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Lock, ShieldAlert } from "lucide-react";
import { setConsent, useConsent } from "@/lib/ui/consent";
import { useAgent } from "@/lib/ui/store";
import { ConnPill } from "@/components/Shell";

export default function ConsentGate() {
  const consent = useConsent();
  const [checked, setChecked] = useState(false);
  const router = useRouter();
  const status = useAgent((s) => s.status);
  const conn = useAgent((s) => s.conn);

  return (
    <div className="mx-auto max-w-xl px-4 py-12">
      <div className="rounded-xl border border-border bg-surface p-6 shadow-2xl">
        <div className="mb-4 flex items-center gap-3">
          <span className="grid h-10 w-10 place-items-center rounded-lg bg-hero/15 text-hero">
            <Lock size={20} aria-hidden />
          </span>
          <div>
            <h1 className="text-xl font-semibold">Enter Azkaban</h1>
            <p className="text-sm text-muted">Privacy forensics for your own device. Nothing leaves this machine.</p>
          </div>
        </div>

        <ul className="mb-5 space-y-2 text-sm text-muted">
          <li>• The dashboard talks only to your local agent at <code className="font-mono text-text">127.0.0.1:8787</code>.</li>
          <li>• Personal data is redacted inside the agent before it ever reaches this page.</li>
          <li>• Capturing someone else&apos;s device or network is illegal in most jurisdictions.</li>
        </ul>

        {consent ? (
          <div className="space-y-4">
            <div className="flex items-center justify-between rounded-lg border border-border bg-raised p-3 text-sm">
              <span>Agent</span>
              <ConnPill />
            </div>
            {conn === "open" && status && (
              <dl className="grid grid-cols-2 gap-2 text-xs text-muted" data-testid="agent-status">
                <dt>Mode</dt><dd className="text-text">{status.mode}</dd>
                <dt>Flows seen</dt><dd className="text-text">{status.flows}</dd>
                <dt>Engines</dt>
                <dd className="text-text">
                  {Object.entries(status.engines).map(([k, v]) => (
                    <span key={k} className={`mr-2 ${v ? "text-success" : "text-muted line-through"}`}>{k}</span>
                  ))}
                </dd>
                <dt>Version</dt><dd className="font-mono text-text">{status.version}</dd>
              </dl>
            )}
            <div className="flex gap-2">
              <button onClick={() => router.push("/radar")} className="flex-1 rounded-lg bg-accent px-4 py-2 font-medium text-bg hover:brightness-110">
                Open the Leak Radar
              </button>
              <button onClick={() => setConsent(false)} className="rounded-lg border border-border px-3 py-2 text-sm text-muted hover:text-text">
                Revoke
              </button>
            </div>
          </div>
        ) : (
          <div className="space-y-4">
            <label className="flex cursor-pointer items-start gap-3 rounded-lg border border-border bg-raised p-3">
              <input
                type="checkbox"
                checked={checked}
                onChange={(e) => setChecked(e.target.checked)}
                className="mt-1 h-4 w-4 accent-[var(--accent)]"
                data-testid="consent-checkbox"
              />
              <span className="text-sm">
                <strong>I own this device &amp; network.</strong> I am only inspecting traffic from hardware and
                accounts that belong to me.
              </span>
            </label>
            <button
              disabled={!checked || consent === null}
              onClick={() => {
                setConsent(true);
                router.push("/radar");
              }}
              className="w-full rounded-lg bg-accent px-4 py-2 font-medium text-bg enabled:hover:brightness-110 disabled:cursor-not-allowed disabled:opacity-40"
            >
              Continue
            </button>
            <p className="flex items-center gap-2 text-xs text-muted">
              <ShieldAlert size={14} aria-hidden /> The agent enforces the same rule: it refuses to capture without
              <code className="font-mono">--i-own-this-device</code>.
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
