// Per-domain page observations for unlisted third parties, persisted in storage.session.
// One "page" = one tab navigation (the extension's exact equivalent of a WhoTracks.me page).
import { browser } from "wxt/browser";
import { classify, insight } from "./clf";
import type { PageObs } from "./trackerFeatures";

export const MIN_PAGES = 3;
const MAX_PAGES = 50;

interface DomainState {
  pages: Record<string, PageObs>; // navKey -> observation
  order: string[];
  reported: boolean;
}

const chains = new Map<string, Promise<unknown>>();

export interface RequestObs {
  domain: string;
  navKey: string;
  type: string;
  bytes: number;
  cookies: boolean;
  uidQs: boolean;
  https: boolean;
  refererLeaked: boolean;
}

/** Record one request; resolves to an unknown_tracker insight the first time the domain is flagged. */
export function observe(r: RequestObs): Promise<ReturnType<typeof insight> | null> {
  const key = `clf:${r.domain}`;
  const run = (chains.get(key) ?? Promise.resolve()).then(async () => {
    const st = ((await browser.storage.session.get(key))[key] as DomainState | undefined) ?? { pages: {}, order: [], reported: false };
    let p = st.pages[r.navKey];
    if (!p) {
      p = { types: [], requests: 0, bytes: 0, cookies: false, uid_qs: false, https: false, referer_leaked: false, samesite_none: null };
      st.pages[r.navKey] = p;
      st.order.push(r.navKey);
      while (st.order.length > MAX_PAGES) delete st.pages[st.order.shift()!];
    }
    if (!p.types.includes(r.type)) p.types.push(r.type);
    p.requests++;
    p.bytes += r.bytes;
    p.cookies ||= r.cookies;
    p.uid_qs ||= r.uidQs;
    p.https ||= r.https;
    p.referer_leaked ||= r.refererLeaked;
    let msg: ReturnType<typeof insight> | null = null;
    if (!st.reported && st.order.length >= MIN_PAGES) {
      const hit = await classify(r.domain, st.order.map((k) => st.pages[k]!));
      if (hit) {
        st.reported = true;
        msg = insight(hit);
        const list = ((await browser.storage.session.get("unknown"))["unknown"] as ReturnType<typeof insight>[] | undefined) ?? [];
        await browser.storage.session.set({ unknown: [msg, ...list.filter((m) => m.key !== msg!.key)].slice(0, 100) });
      }
    }
    await browser.storage.session.set({ [key]: st });
    return msg;
  });
  chains.set(key, run.catch(() => undefined));
  return run;
}
