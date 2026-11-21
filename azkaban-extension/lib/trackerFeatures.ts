// Line-for-line port of azkaban_agent/tracker_features.py (the single source of truth).
// Parity is checked by e2e/feature_parity.mjs against fixtures generated from the Python code.

export const SECOND_LEVEL = new Set(["co", "com", "net", "org", "gov", "ac", "edu", "ne", "or", "go"]);
const COMMON_TLDS = new Set(["com", "net", "org", "io"]);
export const KEYWORDS = ["ad", "ads", "track", "analytic", "metric", "pixel", "tag", "stat", "click", "beacon",
  "collect", "count", "log", "sync", "bid", "data", "cdn", "static", "font", "img", "api", "media"];
export const NGRAM_BUCKETS = 32;

export function registrable(host: string): string {
  const h = host.toLowerCase().replace(/\.+$/, "");
  const labels = h.split(".");
  if (labels.length >= 3 && labels[labels.length - 1]!.length === 2 && SECOND_LEVEL.has(labels[labels.length - 2]!)) {
    return labels.slice(-3).join(".");
  }
  return labels.slice(-2).join(".");
}

function entropy(s: string): number {
  if (!s) return 0;
  const counts = new Map<string, number>();
  for (const c of s) counts.set(c, (counts.get(c) ?? 0) + 1);
  let e = 0;
  for (const v of counts.values()) e -= (v / s.length) * Math.log2(v / s.length);
  return e;
}

export function fnv1a(s: string): number {
  let h = 0x811c9dc5;
  for (const b of new TextEncoder().encode(s)) {
    h ^= b;
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h >>> 0;
}

export function lexical(domain: string): Record<string, number> {
  const reg = registrable(domain);
  const labels = reg.split(".");
  const name = labels[0] ?? "";
  const tld = labels[labels.length - 1] ?? "";
  const f: Record<string, number> = {
    lex_len: name.length,
    lex_entropy: entropy(name),
    lex_digit_ratio: [...name].filter((c) => c >= "0" && c <= "9").length / Math.max(1, name.length),
    lex_hyphens: name.split("-").length - 1,
    lex_vowel_ratio: [...name].filter((c) => "aeiou".includes(c)).length / Math.max(1, name.length),
    lex_tld_cc: tld.length === 2 ? 1 : 0,
    lex_tld_common: COMMON_TLDS.has(tld) ? 1 : 0,
    lex_second_level: labels.length === 3 ? 1 : 0,
  };
  for (const k of KEYWORDS) f[`kw_${k}`] = name.includes(k) ? 1 : 0;
  const grams: string[] = [];
  for (let i = 0; i < Math.max(0, name.length - 2); i++) grams.push(name.slice(i, i + 3));
  if (!grams.length) grams.push(name);
  const buckets = new Array<number>(NGRAM_BUCKETS).fill(0);
  for (const g of grams) buckets[fnv1a(g) % NGRAM_BUCKETS]! += 1;
  const total = buckets.reduce((a, b) => a + b, 0) || 1;
  buckets.forEach((v, i) => (f[`ng_${i}`] = v / total));
  return f;
}

export interface PageObs {
  types: string[]; // script | iframe | beacon | image | stylesheet | font | xhr | media
  requests: number;
  bytes: number;
  cookies: boolean;
  uid_qs: boolean;
  https: boolean;
  referer_leaked: boolean;
  samesite_none: boolean | null; // not observable from an extension -> null
}

const TYPES = ["script", "iframe", "beacon", "image", "stylesheet", "font", "xhr", "media"];

export function behaviourFromPages(pages: PageObs[]): Record<string, number> {
  const n = pages.length;
  if (!n) return { has_behavior: 0 };
  const share = (pred: (p: PageObs) => boolean) => pages.filter(pred).length / n;
  const f: Record<string, number> = {};
  for (const t of TYPES) f[`beh_${t}`] = share((p) => p.types.includes(t));
  f.beh_log_requests = Math.log1p(pages.reduce((a, p) => a + p.requests, 0) / n);
  f.beh_log_content_length = Math.log1p(pages.reduce((a, p) => a + p.bytes, 0) / n);
  f.beh_cookies = share((p) => p.cookies);
  f.beh_bad_qs = share((p) => p.uid_qs);
  f.beh_https = share((p) => p.https);
  f.beh_referer_leaked = share((p) => p.referer_leaked);
  const known = pages.filter((p) => p.samesite_none !== null);
  f.beh_samesite_none = known.length ? known.filter((p) => p.samesite_none).length / known.length : NaN;
  f.has_behavior = 1;
  return f;
}

/** Feature vector in the model's column order; missing values -> training medians. */
export function vector(domain: string, beh: Record<string, number>, columns: string[], medians: Record<string, number>): Float32Array {
  const feats = { ...lexical(domain), ...beh };
  return Float32Array.from(columns.map((c) => {
    const v = feats[c];
    return v === undefined || Number.isNaN(v) ? (medians[c] ?? 0) : v;
  }));
}

// Same UID heuristics as the agent's tracker_clf.py
export const UID_VALUE = /^(?:\d{6,}\.\d{6,}|[0-9a-f]{16,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Za-z0-9_-]{22,})$/i;
export const UID_KEYS = /(^|[._-])(uid|uuid|cid|client_?id|user_?id|device_?id|adid|gaid|idfa|advertiser_?id|vid|sid|fbp|_ga)$/i;

export function uidInQuery(url: URL): boolean {
  for (const [k, v] of [...url.searchParams].slice(0, 50)) if (UID_KEYS.test(k) || UID_VALUE.test(v.trim())) return true;
  return false;
}

/** chrome.webRequest resource type -> WhoTracks.me request type. */
export function webRequestType(t: string): string {
  switch (t) {
    case "script": return "script";
    case "sub_frame": return "iframe";
    case "ping": case "beacon": return "beacon";
    case "image": case "imageset": return "image";
    case "stylesheet": return "stylesheet";
    case "font": return "font";
    case "media": return "media";
    default: return "xhr";
  }
}
