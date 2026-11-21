// When to interrupt the user, and what to say.
//
// Kept separate from the service worker and the content script so the decision is pure and
// testable: deciding is the part that can be wrong, and a toast that fires on every request
// trains the user to ignore it.
//
// Rules:
//   * one toast per subject per page, ever (the dedupe key)
//   * a page gets at most MAX_PER_PAGE toasts, so a hostile page cannot spam
//   * thresholds are high enough that a toast means something happened

export type Severity = "warning" | "critical";

export interface Toast {
  key: string; // dedupe key, unique per subject per page
  message: string;
  severity: Severity;
}

/** Model confidence above which an unlisted domain is worth interrupting for. */
export const UNKNOWN_CONFIDENCE_MIN = 0.85;
/** Third-party request count on one page that is worth mentioning. */
export const THIRD_PARTY_MIN = 20;
/** Fingerprinting surfaces probed before it counts as fingerprinting (probe.content.ts). */
export const MAX_PER_PAGE = 3;

export function unknownTrackerToast(domain: string, confidence: number): Toast | null {
  if (!(confidence >= UNKNOWN_CONFIDENCE_MIN) || !domain) return null;
  return {
    key: `unknown:${domain}`,
    message: `Unknown tracker detected: ${domain} (${Math.round(confidence * 100)}% confidence)`,
    severity: "warning",
  };
}

export function fingerprintToast(blocked: boolean, surfaces: number): Toast {
  return {
    key: "fingerprint",
    message: blocked
      ? "Canvas fingerprinting blocked on this page"
      : `Fingerprinting detected on this page (${surfaces}/6 surfaces probed)`,
    severity: "critical",
  };
}

export function thirdPartyToast(count: number): Toast | null {
  if (count < THIRD_PARTY_MIN) return null;
  // Bucketed so a long-lived page does not re-toast on every request past the threshold.
  return {
    key: `thirdparty:${Math.floor(count / THIRD_PARTY_MIN) * THIRD_PARTY_MIN}`,
    message: `This page made ${count} third-party requests`,
    severity: "warning",
  };
}

/** Per-page dedupe. The service worker is ephemeral, so this lives in storage.session. */
export function shouldSend(sent: string[], key: string): boolean {
  return !sent.includes(key) && sent.length < MAX_PER_PAGE;
}
