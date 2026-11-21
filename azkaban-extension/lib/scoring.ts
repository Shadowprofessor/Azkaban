// Site safety score: one letter for "how exposed am I on this page".
//
// The popup already showed raw counts (requests, Dementors, leaks). Counts need a baseline
// to mean anything — is 12 third parties bad? — so this collapses them into a 0-100 score
// and an A-F grade.
//
// The weights are a deliberate editorial judgement, not a measurement, and the breakdown is
// always shown alongside the grade so the user can see exactly what produced it. Each
// component is capped so no single signal can sink a page on its own, and the caps sum to
// exactly 100: a page can reach F, but only by being bad in several ways at once.

export interface ScoreBreakdown {
  trackerCount: number;
  unknownTrackerCount: number;
  thirdPartyCount: number;
  cookieCount: number;
  fingerprintingDetected: boolean;
}

export interface SiteScore {
  score: number; // 0-100 (100 = safe)
  grade: "A" | "B" | "C" | "D" | "F";
  breakdown: ScoreBreakdown;
  /** Per-signal penalties, so the UI can explain the grade instead of asserting it. */
  penalties: { label: string; points: number }[];
}

export interface ScoreInput {
  trackers?: number; // domains matched against a blocklist
  unknownTrackers?: number; // flagged by the on-device model, on no list
  thirdParties?: number; // distinct third-party registrable domains contacted
  cookies?: number;
  fingerprinting?: boolean;
}

// Penalty caps. These sum to 100.
export const CAP = { trackers: 30, unknown: 24, thirdParty: 20, cookies: 10, fingerprint: 16 } as const;
// Per-unit penalties, and the allowance below which a signal costs nothing.
export const RATE = { trackers: 5, unknown: 8, thirdParty: 2, cookies: 1 } as const;
export const FREE = { thirdParty: 5, cookies: 10 } as const;

const clamp = (n: number, max: number) => Math.min(Math.max(n, 0), max);
const count = (n: number | undefined) => (Number.isFinite(n) ? Math.max(0, Math.trunc(n as number)) : 0);

export function gradeOf(score: number): SiteScore["grade"] {
  return score >= 80 ? "A" : score >= 60 ? "B" : score >= 40 ? "C" : score >= 20 ? "D" : "F";
}

export function computeSiteScore(input: ScoreInput): SiteScore {
  const trackerCount = count(input.trackers);
  const unknownTrackerCount = count(input.unknownTrackers);
  const thirdPartyCount = count(input.thirdParties);
  const cookieCount = count(input.cookies);
  const fingerprintingDetected = !!input.fingerprinting;

  const penalties = [
    { label: "known trackers", points: clamp(trackerCount * RATE.trackers, CAP.trackers) },
    { label: "trackers on no list", points: clamp(unknownTrackerCount * RATE.unknown, CAP.unknown) },
    {
      label: "third parties",
      points: clamp((thirdPartyCount - FREE.thirdParty) * RATE.thirdParty, CAP.thirdParty),
    },
    { label: "cookies", points: clamp((cookieCount - FREE.cookies) * RATE.cookies, CAP.cookies) },
    { label: "fingerprinting", points: fingerprintingDetected ? CAP.fingerprint : 0 },
  ].filter((p) => p.points > 0);

  const penalty = penalties.reduce((n, p) => n + p.points, 0);
  const score = Math.max(100 - penalty, 0);
  return {
    score,
    grade: gradeOf(score),
    breakdown: { trackerCount, unknownTrackerCount, thirdPartyCount, cookieCount, fingerprintingDetected },
    penalties,
  };
}

/** "3 trackers · 1 unknown · 12 third parties · 4 cookies" — only the parts that apply. */
export function breakdownLine(b: ScoreBreakdown): string {
  const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;
  const parts: string[] = [];
  if (b.trackerCount) parts.push(plural(b.trackerCount, "tracker"));
  if (b.unknownTrackerCount) parts.push(`${b.unknownTrackerCount} unknown`);
  if (b.thirdPartyCount) parts.push(plural(b.thirdPartyCount, "third party", "third parties"));
  if (b.cookieCount) parts.push(plural(b.cookieCount, "cookie"));
  if (b.fingerprintingDetected) parts.push("fingerprinting");
  return parts.length ? parts.join(" · ") : "nothing third-party seen yet";
}

/** Grade colour, reusing assets/theme.css variables rather than inventing a palette. */
export function gradeColor(grade: SiteScore["grade"]): string {
  if (grade === "A") return "var(--success)";
  if (grade === "B") return "var(--accent)";
  if (grade === "C") return "var(--warning)";
  return "var(--danger)";
}

/** Badge colour for the toolbar icon, which needs a literal (no CSS vars there). */
export function gradeBadgeColor(grade: SiteScore["grade"]): string {
  if (grade === "A") return "#10b981";
  if (grade === "B") return "#06b6d4";
  if (grade === "C") return "#f59e0b";
  return "#ef4444";
}
