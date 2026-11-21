"use client";

import { useEffect } from "react";
import { AlertOctagon, AlertTriangle, Info, X } from "lucide-react";
import { useAgent } from "@/lib/ui/store";

const STYLE = {
  critical: { icon: AlertOctagon, color: "var(--danger)" },
  error: { icon: AlertOctagon, color: "var(--danger)" },
  warn: { icon: AlertTriangle, color: "var(--warning)" },
  info: { icon: Info, color: "var(--accent)" },
} as const;

export function Toasts() {
  const toasts = useAgent((s) => s.toasts);
  const dismiss = useAgent((s) => s.dismissToast);

  useEffect(() => {
    if (!toasts.length) return;
    const t = setTimeout(() => dismiss(toasts[0].id), toasts[0].level === "critical" ? 9000 : 6000);
    return () => clearTimeout(t);
  }, [toasts, dismiss]);

  return (
    <div aria-live="polite" className="pointer-events-none fixed right-4 bottom-4 z-50 flex w-[min(380px,calc(100vw-2rem))] flex-col gap-2">
      {toasts.map((t) => {
        const { icon: Icon, color } = STYLE[t.level];
        return (
          <div
            key={t.id}
            role={t.level === "critical" ? "alert" : "status"}
            className="azk-enter pointer-events-auto flex gap-3 rounded-lg border bg-raised p-3 shadow-xl"
            style={{ borderColor: color }}
          >
            <Icon size={18} style={{ color }} className="mt-0.5 shrink-0" aria-hidden />
            <div className="min-w-0 flex-1">
              <p className="text-sm font-medium">{t.title}</p>
              {t.detail && <p className="mt-1 line-clamp-3 text-xs text-muted">{t.detail}</p>}
            </div>
            <button onClick={() => dismiss(t.id)} aria-label="Dismiss" className="text-muted hover:text-text">
              <X size={16} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
