// Wire format for the extension -> agent producer channel.
//
// Pure functions, no browser APIs, so the exact bytes the extension sends can be tested
// against the agent's validator (azkaban_agent/extbridge.py) without a browser. The two
// halves are developed in different languages; this is the seam, so it is the thing worth
// pinning down.
import type { SiteScore } from "./scoring";

export interface DetectionPayload {
  kind: string;
  host: string;
  domain?: string;
  site?: string;
  company?: string;
  category?: string;
  confidence?: number;
  bytes?: number;
  severity?: number;
  pii?: readonly { type: string; redacted: string; confidence: number }[];
}

export function helloMsg(extensionVersion: string) {
  return { type: "producer_hello" as const, extension_version: extensionVersion };
}

export function detectionMsg(d: DetectionPayload) {
  return { type: "browser_detection" as const, data: d };
}

/** `site` must be a bare hostname: a full URL would be browsing history. */
export function siteScoreMsg(score: SiteScore, site: string) {
  return {
    type: "site_score" as const,
    data: { site, score: score.score, grade: score.grade, breakdown: score.breakdown },
  };
}

export function pingMsg() {
  return { type: "ping" as const };
}
