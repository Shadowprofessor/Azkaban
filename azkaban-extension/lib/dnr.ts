// Patronus: domain-level blocking with declarativeNetRequest dynamic rules.
// webRequest is observe-only in MV3; DNR does the blocking. Rules carry many domains each
// (requestDomains), so even the full tracker list needs only a handful of rules.
import { browser } from "wxt/browser";
import data from "../../azkaban-agent/azkaban_agent/data/trackers.json";
import type { Settings } from "./store";

const DOMAINS_PER_RULE = 1000;
const RULE_ID_BASE = 1000;

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
  await browser.declarativeNetRequest.updateDynamicRules({
    removeRuleIds: existing.map((r) => r.id),
    addRules: rules,
  });
  return domains.length;
}
