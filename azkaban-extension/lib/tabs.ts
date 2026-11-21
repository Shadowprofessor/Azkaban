// Per-tab counters + toolbar badge. Kept in storage.session so a SW restart loses nothing.
import { browser } from "wxt/browser";

export interface TabStats {
  site: string;
  requests: number;
  trackers: number;
  blocked: number;
  companies: Record<string, number>;
  pii: number;
  fingerprint: number; // distinct fingerprinting surfaces touched (0-6)
  fpFlagged?: boolean; // 5+ surfaces within 2s
  fpFrames?: string[];
  hashed?: number; // outgoing hashes of the user's own identifiers
  domains?: string[];
  unknown?: string[]; // unlisted domains the classifier flagged on this page // third-party registrable domains contacted (for the cookie audit)
  harvest?: { host: string; field: string; via: string; ts: number }[]; // typed before submit, sent anyway
  score?: number;
  grade?: string;
}

const key = (tabId: number) => `tab:${tabId}`;

export async function getTab(tabId: number): Promise<TabStats | null> {
  const r = await browser.storage.session.get(key(tabId));
  return (r[key(tabId)] as TabStats) ?? null;
}

// Serialise per-tab read-modify-write so concurrent webRequest events don't lose counts.
const chains = new Map<number, Promise<unknown>>();

export function bumpTab(tabId: number, site: string, fn: (t: TabStats) => void): Promise<TabStats> {
  const prev = chains.get(tabId) ?? Promise.resolve();
  const next = prev.then(async () => {
    let t = await getTab(tabId);
    if (!t || t.site !== site) t = { site, requests: 0, trackers: 0, blocked: 0, companies: {}, pii: 0, fingerprint: 0 };
    fn(t);
    await browser.storage.session.set({ [key(tabId)]: t });
    await setBadge(tabId, t);
    return t;
  });
  chains.set(tabId, next.catch(() => undefined));
  return next;
}

export async function resetTab(tabId: number): Promise<void> {
  await browser.storage.session.remove([key(tabId), `audit:${tabId}`, `sent:${tabId}`]);
  await browser.action.setBadgeText({ tabId, text: "" }).catch(() => undefined);
}

export async function setBadge(tabId: number, t: TabStats): Promise<void> {
  const n = t.trackers;
  const color = t.grade && "DEF".includes(t.grade) ? "#EF4444" : n > 0 ? "#F59E0B" : "#10B981";
  try {
    await browser.action.setBadgeText({ tabId, text: n ? String(n > 999 ? "999+" : n) : "" });
    await browser.action.setBadgeBackgroundColor({ tabId, color });
  } catch {
    /* tab closed */
  }
}
