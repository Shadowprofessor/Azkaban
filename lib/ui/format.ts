import type { PiiHit } from "@/lib/schema";

export function severityTone(sev: number): { color: string; label: string } {
  if (sev >= 80) return { color: "var(--danger)", label: "Critical" };
  if (sev >= 60) return { color: "#f97316", label: "High" };
  if (sev >= 35) return { color: "var(--warning)", label: "Medium" };
  return { color: "var(--success)", label: "Low" };
}

export const PII_LABEL: Record<PiiHit["type"], string> = {
  email: "Email",
  phone: "Phone",
  imei: "IMEI",
  adid: "Ad ID",
  gps: "GPS",
  contact: "Contacts",
  clipboard: "Clipboard",
};

export function fmtTime(ts: number): string {
  return new Date(ts).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" });
}

export function fmtBytes(n: number): string {
  if (n < 1024) return `${n} B`;
  if (n < 1024 ** 2) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 ** 2).toFixed(1)} MB`;
}

export function flagEmoji(cc: string): string {
  if (!cc || cc === "ZZ" || cc.length !== 2) return "";
  return String.fromCodePoint(...[...cc.toUpperCase()].map((c) => 0x1f1a5 + c.charCodeAt(0)));
}

export const CATEGORY_LABEL: Record<string, string> = {
  tracker_breadth: "Dementor breadth",
  pii_sensitivity: "Data sensitivity",
  consent_violations: "Consent gaps",
  cross_border: "Cross-border",
  hashed_pii: "Hashed identifiers",
};

export const CATEGORY_MAX: Record<string, number> = {
  tracker_breadth: 250,
  pii_sensitivity: 250,
  consent_violations: 200,
  cross_border: 150,
  hashed_pii: 150,
};
