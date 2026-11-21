"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { Activity, FileLock2, Gavel, Network, ShieldCheck, Sparkles } from "lucide-react";
import { useAgent } from "@/lib/ui/store";
import { useConsent } from "@/lib/ui/consent";

const NAV = [
  { href: "/radar", label: "Leak Radar", icon: Activity },
  { href: "/insights", label: "Insights", icon: Sparkles },
  { href: "/legal", label: "Legal", icon: Gavel },
  { href: "/map", label: "Shadow Map", icon: Network },
  { href: "/actions", label: "Patronus", icon: ShieldCheck },
  { href: "/evidence", label: "Evidence", icon: FileLock2 },
];

export function ConnPill() {
  const conn = useAgent((s) => s.conn);
  const status = useAgent((s) => s.status);
  const label =
    conn === "open"
      ? !status?.capturing
        ? "Connected · idle"
        : status.mode === "replay"
          ? "Replaying session"
          : "The Trace: live"
      : conn === "connecting"
        ? "Connecting…"
        : "Agent offline";
  const color = conn === "open" ? "var(--success)" : conn === "connecting" ? "var(--warning)" : "var(--danger)";
  return (
    <span className="inline-flex items-center gap-2 rounded-full border border-border bg-raised px-3 py-1 text-xs" data-testid="conn">
      <span className={`h-2 w-2 rounded-full ${conn !== "offline" ? "azk-pulse" : ""}`} style={{ background: color }} />
      {label}
    </span>
  );
}

export function Shell({ children }: { children: React.ReactNode }) {
  const path = usePathname();
  const consent = useConsent();
  const showNav = consent && path !== "/";
  return (
    <div className="flex min-h-screen flex-col bg-bg text-text">
      <header className="sticky top-0 z-30 flex flex-wrap items-center gap-3 border-b border-border bg-surface/95 px-4 py-2.5 backdrop-blur">
        <Link href={consent ? "/radar" : "/"} className="flex items-center gap-2 font-semibold tracking-wide">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-hero/20 text-hero">Az</span>
          Azkaban
        </Link>
        {showNav && (
          <nav aria-label="Main" className="order-3 flex w-full gap-1 overflow-x-auto [scrollbar-width:none] md:order-none md:w-auto">
            {NAV.map(({ href, label, icon: Icon }) => {
              const active = path.startsWith(href);
              return (
                <Link
                  key={href}
                  href={href}
                  aria-current={active ? "page" : undefined}
                  className={`flex shrink-0 items-center gap-1.5 rounded-md px-3 py-1.5 text-sm ${
                    active ? "bg-raised text-text" : "text-muted hover:bg-raised/60 hover:text-text"
                  }`}
                >
                  <Icon size={15} aria-hidden /> {label}
                </Link>
              );
            })}
          </nav>
        )}
        <div className="ml-auto">{consent && <ConnPill />}</div>
      </header>
      <main className="flex-1">{children}</main>
    </div>
  );
}
