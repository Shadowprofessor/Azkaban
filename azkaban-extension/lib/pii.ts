// TypeScript port of azkaban_agent/pii.py + decode.py + identity.py (subset that runs in a
// service worker). Raw values exist only inside scan(); callers get redacted hits.
import type { PiiHit } from "../../lib/schema";

const EMAIL = /(?<![\w.+-])([A-Za-z0-9._%+-]{1,64})@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,24})(?![\w-])/g;
const UUID = /\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b/g;
const DIGITS15 = /(?<!\d)(\d{15})(?!\d)/g;
const PHONE_E164 = /(?<![\w])\+(\d{1,3})[\s-]?(\d[\d\s-]{6,13}\d)(?!\d)/g;
const PHONE_IN = /(?<!\d)(?:0|91)?([6-9]\d{9})(?!\d)/g;
const LATLNG = /(?<![\d.])(-?\d{1,2}\.\d{4,})\s*,\s*(-?\d{1,3}\.\d{4,})(?![\d.])/g;
const HEXDIGEST = /(?<![0-9a-fA-F])([0-9a-fA-F]{64}|[0-9a-fA-F]{40})(?![0-9a-fA-F])/g;
const ADID_KEYS = /(^|[._[])(adid|ad_id|gaid|aaid|idfa|advertising_?id|advertiser_?id|rdid|ifa)($|[._\]])/i;
const IMEI_KEYS = /imei|device_?id|meid/i;
const PHONE_KEYS = /phone|mobile|msisdn|tel\b|cell/i;
const LAT_KEYS = /(^|[._])(lat|latitude)$/i;
const LNG_KEYS = /(^|[._])(lng|lon|long|longitude)$/i;
const CONTACT_KEYS = /^(contacts?|address_?book|phonebook)$/i;
const CLIP_KEYS = /clipboard|pasteboard|clip_?text/i;
const IMEI_PREFIX = new Set(["01", "30", "33", "35", "44", "45", "49", "50", "51", "52", "53", "54", "86", "91", "98", "99"]);

const MAX_TEXT = 16 * 1024;
const MAX_FIELDS = 1000;
const MAX_INFLATE = 256 * 1024;

export interface Finding {
  type: PiiHit["type"];
  redacted: string;
  confidence: number;
  value: string; // raw: never leaves scan()'s caller in the service worker
  via: string;
}

// ------------------------------------------------------------------ redaction
const tail = (s: string, keep = 4) => {
  const d = s.replace(/\D/g, "");
  return "*".repeat(Math.max(0, d.length - keep)) + d.slice(-keep);
};
const redEmail = (local: string, dom: string) => {
  const i = dom.lastIndexOf(".");
  return `${local[0]}***@${dom[0]}***.${dom.slice(i + 1)}`;
};
const redId = (s: string) => `${s.slice(0, 4)}****-****${s.slice(-4)}`;
const redGps = (a: number, b: number) => `${a.toFixed(1)},${b.toFixed(1)} (~11km)`;

function luhn(n: string) {
  let sum = 0;
  for (let i = 0; i < n.length; i++) {
    let d = Number(n[n.length - 1 - i]);
    if (i % 2) {
      d *= 2;
      if (d > 9) d -= 9;
    }
    sum += d;
  }
  return sum % 10 === 0;
}

// ------------------------------------------------------------------ fields
type Pair = [string, string];

function flatten(obj: unknown, prefix: string, out: Pair[], depth = 0) {
  if (out.length >= MAX_FIELDS) return;
  if (depth > 32) return;
  if (Array.isArray(obj)) obj.forEach((v, i) => flatten(v, `${prefix}[${i}]`, out, depth + 1));
  else if (obj && typeof obj === "object") for (const [k, v] of Object.entries(obj)) flatten(v, prefix ? `${prefix}.${k}` : k, out, depth + 1);
  else if (obj !== null && obj !== undefined) out.push([prefix, String(obj)]);
}

function tooDeep(t: string, limit = 64) {
  let d = 0;
  for (const c of t) {
    if (c === "{" || c === "[") {
      if (++d > limit) return true;
    } else if (c === "}" || c === "]") d--;
  }
  return false;
}

export function parseText(text: string, prefix = "", depth = 0): Pair[] {
  const t = text.trim().slice(0, MAX_TEXT);
  if (!t) return [];
  if (depth > 4) return [[prefix || "body", t]];
  if ((t[0] === "{" || t[0] === "[") && !tooDeep(t)) {
    try {
      const out: Pair[] = [];
      flatten(JSON.parse(t), prefix, out);
      return out;
    } catch {
      /* fall through */
    }
  }
  if (t.includes("=") && !t.includes("\n") && !t.slice(0, 200).includes(" ")) {
    const out: Pair[] = [];
    for (const [k, v] of new URLSearchParams(t)) {
      const key = prefix ? `${prefix}.${k}` : k;
      out.push(...(v[0] === "{" || v[0] === "[" ? parseText(v, key, depth + 1) : [[key, v] as Pair]));
      if (out.length >= MAX_FIELDS) break;
    }
    if (out.length) return out;
  }
  return [[prefix || "body", t]];
}

// ------------------------------------------------------------------ decoding layers
function printable(s: string) {
  if (!s) return false;
  let ok = 0;
  for (const c of s) if (c >= " " || c === "\n" || c === "\t" || c === "\r") ok++;
  return ok / s.length > 0.9;
}

function utf8(bytes: Uint8Array): string | null {
  try {
    return new TextDecoder("utf-8", { fatal: true }).decode(bytes);
  } catch {
    return null;
  }
}

async function inflate(bytes: Uint8Array): Promise<Uint8Array | null> {
  const fmt = bytes[0] === 0x1f && bytes[1] === 0x8b ? "gzip" : bytes[0] === 0x78 ? "deflate" : null;
  if (!fmt) return null;
  try {
    const reader = new Blob([new Uint8Array(bytes)]).stream().pipeThrough(new DecompressionStream(fmt)).getReader();
    const chunks: Uint8Array[] = [];
    let total = 0;
    while (total < MAX_INFLATE) {
      const { value, done } = await reader.read();
      if (done) break;
      chunks.push(value);
      total += value.length;
    }
    await reader.cancel().catch(() => undefined); // bomb guard: stop after the cap
    const out = new Uint8Array(Math.min(total, MAX_INFLATE));
    let o = 0;
    for (const c of chunks) {
      out.set(c.subarray(0, out.length - o), o);
      o += c.length;
      if (o >= out.length) break;
    }
    return out;
  } catch {
    return null;
  }
}

async function unwrap(v: string): Promise<[string, string][]> {
  const out: [string, string][] = [];
  const s = v.trim().slice(0, MAX_TEXT);
  if (s.includes("%")) {
    try {
      const u = decodeURIComponent(s.replace(/\+/g, " "));
      if (u !== s) out.push(["url", u]);
    } catch {
      /* malformed escape */
    }
  }
  if (/^[A-Za-z0-9+/_-]{12,}={0,2}$/.test(s) && ![40, 64].includes(s.length)) {
    try {
      const b = Uint8Array.from(atob(s.replace(/-/g, "+").replace(/_/g, "/") + "=".repeat((4 - (s.length % 4)) % 4)), (c) => c.charCodeAt(0));
      const z = await inflate(b);
      const t = utf8(z ?? b);
      if (t && t.length >= 4 && printable(t)) out.push([z ? "base64+gzip" : "base64", t]);
    } catch {
      /* not base64 */
    }
  }
  if (/^(?:[0-9a-fA-F]{2}){8,}$/.test(s) && ![40, 64].includes(s.length)) {
    const b = Uint8Array.from(s.match(/../g)!.map((h) => parseInt(h, 16)));
    const t = utf8(b);
    if (t && printable(t)) out.push(["hex", t]);
  }
  return out;
}

async function expand(pairs: Pair[]): Promise<[string, string, string][]> {
  const result: [string, string, string][] = pairs.map(([k, v]) => [k, v, ""]);
  let frontier = result;
  for (let depth = 0; depth < 2 && frontier.length; depth++) {
    const next: [string, string, string][] = [];
    for (const [k, v, via] of frontier.slice(0, MAX_FIELDS)) {
      for (const [layer, text] of await unwrap(v)) {
        for (const [k2, v2] of parseText(text, k)) next.push([k2, v2, via ? `${via}>${layer}` : layer]);
      }
    }
    result.push(...next);
    frontier = next;
  }
  return result;
}

// ------------------------------------------------------------------ detectors
function scanPair(key: string, value: string, via: string): Finding[] {
  const out: Finding[] = [];
  const v = value.slice(0, 20000);
  const tag = (f: Omit<Finding, "via">): Finding => ({ ...f, via, redacted: via ? `${f.redacted} [${via}]` : f.redacted });
  for (const m of v.matchAll(EMAIL)) out.push(tag({ type: "email", value: `${(m[1] ?? "")}@${(m[2] ?? "")}`.toLowerCase(), redacted: redEmail((m[1] ?? ""), (m[2] ?? "")), confidence: 0.95 }));
  if (ADID_KEYS.test(key)) for (const m of v.matchAll(UUID)) if (!/^0{8}-/.test((m[0] ?? ""))) out.push(tag({ type: "adid", value: (m[0] ?? "").toLowerCase(), redacted: redId((m[0] ?? "")), confidence: 0.95 }));
  for (const m of v.matchAll(DIGITS15)) if (luhn((m[1] ?? "")) && IMEI_PREFIX.has((m[1] ?? "").slice(0, 2))) out.push(tag({ type: "imei", value: (m[1] ?? ""), redacted: (m[1] ?? "").slice(0, 2) + tail((m[1] ?? "")).slice(2), confidence: IMEI_KEYS.test(key) ? 0.95 : 0.6 }));
  const phoneKey = PHONE_KEYS.test(key);
  for (const m of v.matchAll(PHONE_E164)) {
    const raw = "+" + (m[1] ?? "") + (m[2] ?? "").replace(/\D/g, "");
    if (raw.length >= 9 && raw.length <= 16) out.push(tag({ type: "phone", value: raw, redacted: "+" + (m[1] ?? "") + tail((m[2] ?? ""), 3).slice(-10), confidence: phoneKey ? 0.9 : 0.7 }));
  }
  if (phoneKey) for (const m of v.matchAll(PHONE_IN)) out.push(tag({ type: "phone", value: "+91" + (m[1] ?? ""), redacted: "+91" + tail((m[1] ?? ""), 3), confidence: 0.85 }));
  for (const m of v.matchAll(LATLNG)) {
    const a = Number((m[1] ?? "")), b = Number((m[2] ?? ""));
    if (Math.abs(a) <= 90 && Math.abs(b) <= 180 && (a || b)) out.push(tag({ type: "gps", value: `${a},${b}`, redacted: redGps(a, b), confidence: 0.8 }));
  }
  const leaf = key.split(".").at(-1)!.replace(/\[\d+\]/g, "");
  if (CONTACT_KEYS.test(leaf) && !key.includes("[")) out.push(tag({ type: "contact", value: `${key}:${v.slice(0, 64)}`, redacted: `contact data in '${leaf}'`, confidence: 0.75 }));
  if (CLIP_KEYS.test(leaf)) out.push(tag({ type: "clipboard", value: v.slice(0, 256), redacted: `<clipboard ${v.length} chars>`, confidence: 0.9 }));
  return out;
}

function gpsPairs(pairs: Pair[]): Finding[] {
  const parent = (k: string) => (k.includes(".") ? k.slice(0, k.lastIndexOf(".")) : "");
  const lats = new Map<string, string>(), lngs = new Map<string, string>();
  for (const [k, v] of pairs) {
    if (!/^-?\d{1,3}\.\d{3,}$/.test(v.trim())) continue;
    if (LAT_KEYS.test(k)) lats.set(parent(k), v);
    else if (LNG_KEYS.test(k)) lngs.set(parent(k), v);
  }
  const out: Finding[] = [];
  for (const [p, la] of lats) {
    const lo = lngs.get(p);
    if (lo) out.push({ type: "gps", value: `${la},${lo}`, redacted: redGps(Number(la), Number(lo)), confidence: 0.9, via: "" });
  }
  return out;
}

export interface ScanResult {
  findings: Finding[];
  hashedHits: number;
}

/** knownHashes: sha256/sha1 hex of the user's own identifiers (see options page). */
export async function scan(url: string, body: string, knownHashes: Set<string>): Promise<ScanResult> {
  const pairs: Pair[] = [];
  try {
    const u = new URL(url);
    for (const [k, v] of u.searchParams) pairs.push([k, v]);
  } catch {
    /* relative or malformed */
  }
  if (body) pairs.push(...parseText(body));
  const layers = await expand(pairs.slice(0, MAX_FIELDS));
  const found: Finding[] = [];
  let hashedHits = 0;
  for (const [k, v, via] of layers) {
    found.push(...scanPair(k, v, via));
    if (knownHashes.size) {
      for (const m of v.matchAll(HEXDIGEST)) {
        const h = (m[1] ?? "").toLowerCase();
        if (knownHashes.has(h)) {
          hashedHits++;
          const algo = h.length === 64 ? "sha256" : "sha1";
          found.push({ type: "email", value: h, redacted: `${algo}(one of your identifiers)`, confidence: 0.99, via: via ? `${via}>${algo}` : algo });
        }
      }
    }
  }
  found.push(...gpsPairs(layers.map(([k, v]) => [k, v] as Pair)));
  const best = new Map<string, Finding>();
  for (const f of found) {
    const fam = /sha/.test(f.via) ? "hash" : f.via ? "enc" : "plain";
    const key = `${f.type}|${f.value}|${fam}`;
    if (!best.has(key) || best.get(key)!.confidence < f.confidence) best.set(key, f);
  }
  const plain = new Set([...best.keys()].filter((k) => k.endsWith("|plain")).map((k) => k.slice(0, -6)));
  return { findings: [...best.entries()].filter(([k]) => !(k.endsWith("|enc") && plain.has(k.slice(0, -4)))).map(([, f]) => f), hashedHits };
}

export function toHits(f: Finding[]): PiiHit[] {
  return f.map(({ type, redacted, confidence }) => ({ type, redacted, confidence: Math.round(confidence * 100) / 100 }));
}

// ------------------------------------------------------------------ known identifiers
export async function digest(algo: "SHA-256" | "SHA-1", s: string): Promise<string> {
  const buf = await crypto.subtle.digest(algo, new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/** Hash an identifier's common normalisations. The raw value is discarded by the caller. */
export async function hashIdentifier(raw: string): Promise<string[]> {
  const v = raw.trim();
  const variants = new Set([v, v.toLowerCase()]);
  const digits = v.replace(/\D/g, "");
  if (digits.length >= 8 && !v.includes("@")) {
    variants.add(digits).add("+" + digits);
    if (digits.length > 10) variants.add(digits.slice(-10));
  }
  const out: string[] = [];
  for (const x of variants) out.push(await digest("SHA-256", x), await digest("SHA-1", x));
  return out;
}
