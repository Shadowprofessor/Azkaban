"use client";

import { Guard } from "@/components/Guard";
import { useAgent } from "@/lib/ui/store";

export default function RadarPage() {
  const n = useAgent((s) => s.flows.length);
  return (
    <Guard>
      <p className="p-4 text-muted" data-testid="flow-count">{n} flows</p>
    </Guard>
  );
}
