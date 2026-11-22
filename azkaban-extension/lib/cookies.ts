// Live cookie inspection and cookie blocking.
//
// Blocking has two halves:
//  - network: DNR rules (lib/dnr.ts) strip Cookie on the way out and Set-Cookie on the way in;
//  - storage: cookies already in the jar, or written by page script (document.cookie, which
//    no header rule can see), are removed here.
// Nothing in this file stores a cookie value. Pages that show values read them live from
// browser.cookies and keep them only in the DOM while open.
import { browser } from "wxt/browser";
import { registrable } from "./domain";
import { TRACKING_COOKIE } from "./audit";

export interface CookieLike {
  name: string;
  domain: string;
  path: string;
  secure: boolean;
  httpOnly: boolean;
  sameSite: string;
  session?: boolean;
  expirationDate?: number;
  storeId?: string;
  value?: string;
}

const YEAR_S = 365 * 24 * 3600;

export const bareDomain = (d: string) => d.replace(/^\./, "").toLowerCase();

/** True when the cookie's domain is a blocked domain or a subdomain of one. */
export function isCookieBlocked(cookieDomain: string, blocks: readonly string[]): boolean {
  const d = bareDomain(cookieDomain);
  return blocks.some((b) => d === b || d.endsWith(`.${b}`));
}

/** The URL browser.cookies.remove needs to address one exact cookie. */
export function cookieUrl(c: Pick<CookieLike, "domain" | "path" | "secure">): string {
  return `http${c.secure ? "s" : ""}://${bareDomain(c.domain)}${c.path || "/"}`;
}

export interface CookieFacts {
  thirdParty: boolean;
  tracking: boolean;
  longLived: boolean;
  session: boolean;
  /** Days until expiry, null for session cookies. */
  days: number | null;
}

export function cookieFacts(c: CookieLike, site: string, now = Date.now() / 1000): CookieFacts {
  const session = c.session ?? !c.expirationDate;
  const left = c.expirationDate ? c.expirationDate - now : 0;
  return {
    thirdParty: !!site && registrable(bareDomain(c.domain)) !== site,
    tracking: TRACKING_COOKIE.test(c.name),
    longLived: !session && left > YEAR_S,
    session,
    days: session ? null : Math.max(0, Math.round(left / 86400)),
  };
}

export async function removeCookie(c: CookieLike): Promise<boolean> {
  const r = await browser.cookies
    .remove({ url: cookieUrl(c), name: c.name, ...(c.storeId ? { storeId: c.storeId } : {}) })
    .catch(() => null);
  return !!r;
}

/** Delete every cookie a domain (and its subdomains) holds. Returns how many went. */
export async function purgeDomain(domain: string): Promise<number> {
  const all = await browser.cookies.getAll({ domain }).catch(() => [] as CookieLike[]);
  let n = 0;
  for (const c of all) if (await removeCookie(c)) n++;
  return n;
}
