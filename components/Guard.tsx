"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useConsent } from "@/lib/ui/consent";
import { useAgent } from "@/lib/ui/store";
import { Loader2, PlugZap } from "lucide-react";

/** Blocks a route until consent is given; shows an offline banner over stale data. */
export function Guard({ children }: { children: React.ReactNode }) {
  const consent = useConsent();
  const router = useRouter();
  const conn = useAgent((s) => s.conn);
  const hasData = useAgent((s) => s.lastMessageAt !== null);

  useEffect(() => {
    if (consent === false) router.replace("/");
  }, [consent, router]);

  if (consent !== true) {
    return (
      <div className="grid min-h-[50vh] place-items-center text-muted">
        <Loader2 className="animate-spin" aria-label="Loading" />
      </div>
    );
  }
  return (
    <>
      {conn === "offline" && (
        <div role="status" className="flex items-center gap-2 border-b border-danger/40 bg-danger/10 px-4 py-2 text-sm">
          <PlugZap size={16} className="text-danger" aria-hidden />
          Agent offline — {hasData ? "showing the last state received. " : ""}reconnecting automatically. Start it with{" "}
          <code className="font-mono text-xs">python -m azkaban_agent replay azkaban-agent/demo/demo.azk</code>
        </div>
      )}
      {children}
    </>
  );
}
