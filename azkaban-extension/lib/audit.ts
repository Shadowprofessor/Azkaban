// Cookie + storage audit. Values are never stored: ID-like values are reduced to a
// truncated SHA-256 so the same identifier can be recognised across places.
import { browser } from "wxt/browser";
import { registrable } from "./domain";
import { isTrackerDomain } from "./trackers";
import { digest } from "./pii";

export const TRACKING_COOKIE = /^(_ga|_gid|_gat|_gcl_\w+|__utm\w|_fbp|_fbc|fr|IDE|DSID|NID|ANID|1P_JAR|MUID|_uetvid|_uetsid|_ttp|_tt_\w+|_pin_unauth|_scid|_sctr|li_\w+|bcookie|lidc|uid|uuid|__qca|_hj\w+|ajs_\w+|mp_\w+|amplitude_\w+|_clck|_clsk|AMCV_\w+|s_vi|s_ecid|tuuid|tluid|cto_\w+|criteo\w*|KTPCACOOKIE|ad-id|ad-privacy)$/i;
const ID_LIKE = /^(?:\d{6,}\.\d{6,}|[0-9a-f]{16,}|[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|[A-Za-z0-9_-]{22,}|GA\d\.\d\.\d+\.\d+|fb\.\d\.\d+\.\d+)$/i;
const YEAR_S = 365 * 24 * 3600;

export const idHash = async (v: string) => (await digest("SHA-256", v)).slice(0, 16);

/** Pulls the stable ID part out of common formats (GA1.2.123.456 -> 123.456). */
export function idCore(v: string): string | null {
  const s = decodeURIComponentSafe(v).trim();
  const ga = s.match(/^GA\d\.\d\.(\d+\.\d+)$/);
  if (ga?.[1]) return ga[1];
  const fb = s.match(/^fb\.\d\.\d+\.(\d+)$/);
  if (fb?.[1]) return fb[1];
  return ID_LIKE.test(s) && s.length <= 128 ? s : null;
}

function decodeURIComponentSafe(v: string) {
  try {
    return decodeURIComponent(v);
  } catch {
    return v;
  }
}

export interface CookieAudit {
  site: string;
  total: number;
  thirdParty: number;
  longLived: number;
  tracking: number;
  insecure: number; // SameSite=None without Secure, or session-identifying without HttpOnly
  trackers: string[]; // tracker domains holding cookies
  ids: Record<string, string[]>; // idHash -> domains holding that ID
}

export async function auditCookies(site: string, pageUrl: string): Promise<CookieAudit> {
  const cookies = await browser.cookies.getAll({ url: pageUrl }).catch(() => []);
  // Third-party cookies a page can use are not returned for its URL; include tracker
  // domains this tab contacted is done by the caller via extraDomains.
  const res: CookieAudit = { site, total: 0, thirdParty: 0, longLived: 0, tracking: 0, insecure: 0, trackers: [], ids: {} };
  await addCookies(res, cookies, site);
  return res;
}

export async function addCookies(res: CookieAudit, cookies: { name: string; value: string; domain: string; expirationDate?: number; secure: boolean; httpOnly: boolean; sameSite: string }[], site: string) {
  const now = Date.now() / 1000;
  for (const c of cookies) {
    res.total++;
    const dom = registrable(c.domain.replace(/^\./, ""));
    if (dom !== site) res.thirdParty++;
    if (c.expirationDate && c.expirationDate - now > YEAR_S) res.longLived++;
    if (TRACKING_COOKIE.test(c.name)) res.tracking++;
    if (c.sameSite === "no_restriction" && !c.secure) res.insecure++;
    if (isTrackerDomain(dom) && !res.trackers.includes(dom)) res.trackers.push(dom);
    const core = idCore(c.value);
    if (core) {
      const h = await idHash(core);
      const list = (res.ids[h] ??= []);
      if (!list.includes(dom)) list.push(dom);
    }
  }
}

export interface StorageReport {
  origin: string;
  localKeys: number;
  idKeys: string[]; // key names only
  idHashes: string[]; // truncated hashes of ID-like values
  indexedDb: string[];
}

export interface SiteAudit {
  cookies: CookieAudit;
  storage: StorageReport[];
  supercookies: { hash: string; places: string[] }[]; // same ID in cookie + web storage
  synced: { hash: string; domains: string[] }[]; // same ID across registrable domains
  ts: number;
}

export function combine(cookies: CookieAudit, storage: StorageReport[], sentTo: Record<string, string[]>): SiteAudit {
  const places = new Map<string, Set<string>>();
  const add = (h: string, p: string) => (places.get(h) ?? places.set(h, new Set()).get(h)!).add(p);
  for (const [h, doms] of Object.entries(cookies.ids)) doms.forEach((d) => add(h, `cookie@${d}`));
  for (const s of storage) {
    let host = s.origin;
    try {
      host = new URL(s.origin).hostname;
    } catch {
      /* keep as is */
    }
    for (const h of s.idHashes) add(h, `localStorage@${registrable(host)}`);
  }
  const supercookies = [...places.entries()]
    .filter(([, p]) => [...p].some((x) => x.startsWith("cookie")) && [...p].some((x) => x.startsWith("localStorage")))
    .map(([hash, p]) => ({ hash, places: [...p] }));
  const domains = new Map<string, Set<string>>();
  for (const [h, doms] of Object.entries(cookies.ids)) doms.forEach((d) => (domains.get(h) ?? domains.set(h, new Set()).get(h)!).add(d));
  for (const [h, doms] of Object.entries(sentTo)) doms.forEach((d) => (domains.get(h) ?? domains.set(h, new Set()).get(h)!).add(d));
  const synced = [...domains.entries()].filter(([, d]) => d.size >= 2).map(([hash, d]) => ({ hash, domains: [...d] }));
  return { cookies, storage, supercookies, synced, ts: Date.now() };
}
