"use client";

import { Moon, Pause, Play } from "lucide-react";
import { useAgent } from "@/lib/ui/store";
import { sendCommand } from "@/lib/ui/socket";

export function Controls() {
  const status = useAgent((s) => s.status);
  const conn = useAgent((s) => s.conn);
  const idle = useAgent((s) => s.insights["idle_beacons"]);
  const count = (idle?.data as { count?: number } | undefined)?.count ?? 0;
  const capturing = !!status?.capturing;
  const disabled = conn !== "open";

  return (
    <div className="flex flex-wrap items-center gap-3">
      <button
        disabled={disabled}
        onClick={() => sendCommand({ type: capturing ? "stop" : "start" })}
        className={`inline-flex items-center gap-2 rounded-lg px-3 py-1.5 text-sm font-medium disabled:opacity-40 ${
          capturing ? "border border-border bg-raised hover:bg-border" : "bg-accent text-bg hover:brightness-110"
        }`}
      >
        {capturing ? <Pause size={15} aria-hidden /> : <Play size={15} aria-hidden />}
        {capturing ? "Stop The Trace" : status?.mode === "idle" || !status ? "Start The Trace" : "Resume"}
      </button>
      <div
        className="inline-flex items-center gap-2 rounded-lg border border-border bg-surface px-3 py-1.5 text-sm"
        title="Tracker requests sent while you weren't touching the keyboard or mouse"
        data-testid="idle-counter"
      >
        <Moon size={15} className="text-hero" aria-hidden />
        <span className="font-mono font-semibold tabular-nums">{count}</span>
        <span className="text-muted">phone-homes while idle</span>
      </div>
      {status && (
        <span className="text-xs text-muted">
          {status.flows} flows · {status.proxy ? <span className="font-mono">{status.proxy}</span> : status.mode}
        </span>
      )}
    </div>
  );
}
