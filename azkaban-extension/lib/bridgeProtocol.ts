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

/** The fields of a captured request the agent may receive. No query values, header values,
 * cookie values or bodies: names and sizes only. */
export interface WireFlow {
  id: string; ts: number; site: string; host: string; method: string; path: string; ip: string;
  bytes: number; status: number; rtype: string; ms: number; scheme: string; thirdParty: boolean;
  cookieSent: boolean; setCookies: string[]; blocked: string; queryKeys: string[];
}

export function toWireFlow(f: {
  id: string; ts: number; initiator?: string; app?: string; host: string; method: string; path: string;
  ip?: string; bytes?: number; status?: number; rtype?: string; ms?: number; scheme?: string;
  thirdParty?: boolean; cookieSent?: boolean; setCookies?: string[]; blocked?: string; queryKeys?: string[];
}): WireFlow {
  return {
    id: f.id.slice(0, 64), ts: f.ts, site: f.initiator || f.app || "", host: f.host, method: f.method,
    path: (f.path || "/").split("?")[0]!.slice(0, 2048), ip: f.ip ?? "", bytes: f.bytes ?? 0,
    status: f.status ?? 0, rtype: f.rtype ?? "other", ms: f.ms ?? 0, scheme: f.scheme ?? "",
    thirdParty: !!f.thirdParty, cookieSent: !!f.cookieSent, setCookies: (f.setCookies ?? []).slice(0, 20),
    blocked: f.blocked ?? "", queryKeys: (f.queryKeys ?? []).slice(0, 30),
  };
}

export function flowsMsg(flows: WireFlow[]) {
  return { type: "browser_flows" as const, data: flows };
}

export function pingMsg() {
  return { type: "ping" as const };
}
