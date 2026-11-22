// Patronus: domain-level blocking with declarativeNetRequest dynamic rules.
// webRequest is observe-only in MV3; DNR does the blocking. Rules carry many domains each
// (requestDomains), so even the full tracker list needs only a handful of rules.
import { browser } from "wxt/browser";
import data from "../../azkaban-agent/azkaban_agent/data/trackers.json";
import type { Settings } from "./store";

const DOMAINS_PER_RULE = 1000;
const RULE_ID_BASE = 1000;
const COOKIE_RULE_BASE = 9000;
const DOMAIN_RE = /^[a-z0-9.-]+\.[a-z]{2,}$/i;

// Every resource type, main_frame included: blocking a domain's cookies has to hold when you
// visit that domain directly, not only when another site embeds it.
const ALL_TYPES = [
  "main_frame", "sub_frame", "stylesheet", "script", "image", "font", "object", "xmlhttprequest",
  "ping", "csp_report", "media", "websocket", "webtransport", "webbundle", "other",
] as const;

const STRIP_COOKIES = {
  type: "modifyHeaders" as const,
  requestHeaders: [{ header: "cookie", operation: "remove" as const }],
  responseHeaders: [{ header: "set-cookie", operation: "remove" as const }],
};

export function cookieBlockedDomains(s: Settings): string[] {
  return [...new Set(s.cookieBlocks ?? [])].filter((d) => DOMAIN_RE.test(d)).sort();
}

/** Cookie rules: strip Cookie going out and Set-Cookie coming back. Pure, so it is testable. */
export function cookieRules(s: Settings) {
  const rules = [];
  const doms = cookieBlockedDomains(s);
  for (let i = 0; i < doms.length; i += DOMAINS_PER_RULE) {
    rules.push({
      id: COOKIE_RULE_BASE + rules.length,
      priority: 2,
      action: STRIP_COOKIES,
      condition: { requestDomains: doms.slice(i, i + DOMAINS_PER_RULE), resourceTypes: [...ALL_TYPES] },
    });
  }
  if (s.blockThirdPartyCookies) {
    rules.push({
      id: COOKIE_RULE_BASE + 900,
      priority: 1,
      action: STRIP_COOKIES,
      condition: {
        domainType: "thirdParty" as const,
        resourceTypes: ALL_TYPES.filter((t) => t !== "main_frame"),
        ...(s.allowlist.length ? { excludedInitiatorDomains: s.allowlist } : {}),
      },
    });
  }
  return rules;
}

const ALL_TRACKER_DOMAINS = Object.keys((data as { trackers: Record<string, unknown> }).trackers);

export function blockedDomains(s: Settings): string[] {
  const set = new Set<string>(s.customBlocks);
  if (s.blockTrackers) ALL_TRACKER_DOMAINS.forEach((d) => set.add(d));
  return [...set].filter((d) => /^[a-z0-9.-]+\.[a-z]{2,}$/i.test(d)).sort();
}

export async function syncRules(s: Settings): Promise<number> {
  const domains = blockedDomains(s);
  const existing = await browser.declarativeNetRequest.getDynamicRules();
  const max = browser.declarativeNetRequest.MAX_NUMBER_OF_DYNAMIC_RULES ?? 5000;
  const rules: Parameters<typeof browser.declarativeNetRequest.updateDynamicRules>[0]["addRules"] = [];
  for (let i = 0; i < domains.length && rules!.length < max; i += DOMAINS_PER_RULE) {
    rules!.push({
      id: RULE_ID_BASE + rules!.length,
      priority: 1,
      action: { type: "block" },
      condition: {
        requestDomains: domains.slice(i, i + DOMAINS_PER_RULE),
        domainType: "thirdParty", // never block the site you are actually visiting
        ...(s.allowlist.length ? { excludedInitiatorDomains: s.allowlist } : {}), // "site broken? pause here"
      },
    });
  }
  for (const r of cookieRules(s)) if (rules!.length < max) rules!.push(r as (typeof rules)[number]);
  await browser.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: existing.map((r) => r.id),
    addRules: rules,
  });
  return domains.length;
}
