import { defineBackground } from "wxt/utils/define-background";
import { browser } from "wxt/browser";
import { hostOf, isWebUrl, registrable } from "../lib/domain";
import { appendFlow, attachFindings, getSettings, type ExtFlow } from "../lib/store";
import { scan, toHits } from "../lib/pii";
import { addCookies, auditCookies, combine, idCore, idHash, type StorageReport } from "../lib/audit";
import { lookup } from "../lib/trackers";
import { bumpTab, getTab, resetTab } from "../lib/tabs";
import { syncRules } from "../lib/dnr";
import { setSettings } from "../lib/store";

// Per-request scratch (requestId -> partial). Requests finish within seconds while the SW is
// awake handling their events; nothing here needs to survive a SW restart.
const pending = new Map<string, { ts: number; reqBytes: number }>();

function bodySize(details: { requestBody?: { raw?: { bytes?: ArrayBuffer }[]; formData?: Record<string, unknown[]> } | null }) {
  const rb = details.requestBody;
  if (!rb) return 0;
  if (rb.raw) return rb.raw.reduce((n, p) => n + (p.bytes?.byteLength ?? 0), 0);
  if (rb.formData) return JSON.stringify(rb.formData).length;
  return 0;
}

// Body scanning: raw bodies live only for the duration of this function. Only redacted
// findings are stored.
async function handleBody(tabId: number, site: string, url: string, method: string, body: string) {
  try {
    const settings = await getSettings();
    const { findings, hashedHits } = await scan(url, body, new Set(settings.knownHashes));
    if (!findings.length) return;
    const u = new URL(url);
    const { tracker, company } = lookup(u.hostname);
    const thirdParty = registrable(u.hostname) !== site;
    const flow: ExtFlow = {
      id: `ext-body-${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
      ts: Date.now(), app: site, host: u.hostname, method, path: u.pathname, ip: "", country: "ZZ",
      company, tracker, decrypted: true, pii: toHits(findings), severity: 0, tcf: null,
      bytes: body.length, thirdParty, source: "extension", initiator: site,
      findings: hashedHits ? [{ kind: "hashed_pii", detail: `${hashedHits} hashed identifier(s) of yours` }] : [],
    };
    await attachFindings(flow);
    await bumpTab(tabId, site, (t) => {
      t.pii += findings.length;
      if (hashedHits) t.hashed = (t.hashed ?? 0) + hashedHits;
    });
  } catch {
    /* one bad body never breaks the worker */
  }
}

// ID-like query values sent to third parties, as truncated hashes, for sync detection.
async function recordSentIds(tabId: number, url: URL) {
  try {
    const key = `sent:${tabId}`;
    const cur = ((await browser.storage.session.get(key))[key] as Record<string, string[]>) ?? {};
    let changed = false;
    const dom = registrable(url.hostname);
    for (const [, v] of [...url.searchParams].slice(0, 50)) {
      const core = idCore(v);
      if (!core) continue;
      const h = await idHash(core);
      const list = (cur[h] ??= []);
      if (!list.includes(dom)) {
        list.push(dom);
        changed = true;
      }
    }
    if (changed) await browser.storage.session.set({ [key]: cur });
  } catch {
    /* ignore */
  }
}

async function runAudit(tabId: number) {
  try {
    const tab = await browser.tabs.get(tabId);
    if (!isWebUrl(tab.url)) return null;
    const site = registrable(hostOf(tab.url));
    const cookies = await auditCookies(site, tab.url!);
    const stats = await getTab(tabId);
    for (const dom of stats?.domains ?? []) {
      const third = await browser.cookies.getAll({ domain: dom }).catch(() => []);
      await addCookies(cookies, third, site);
    }
    const storage = ((await browser.tabs.sendMessage(tabId, { type: "storage_audit" }, { frameId: 0 }).catch(() => null)) as StorageReport | null);
    const sentKey = `sent:${tabId}`;
    const sent = ((await browser.storage.session.get(sentKey))[sentKey] as Record<string, string[]>) ?? {};
    const audit = combine(cookies, storage ? [storage] : [], sent);
    await browser.storage.session.set({ [`audit:${tabId}`]: audit });
    return audit;
  } catch {
    return null;
  }
}

type PatronusCmd =
  | { type: "patronus"; action: "toggle"; on: boolean }
  | { type: "patronus"; action: "block"; domains: string[] }
  | { type: "patronus"; action: "unblock"; domains: string[] }
  | { type: "patronus"; action: "pause"; site: string }
  | { type: "patronus"; action: "resume"; site: string };

const DOMAIN = /^[a-z0-9.-]+\.[a-z]{2,}$/i;

async function patronus(c: PatronusCmd) {
  const s = await getSettings();
  if (c.action === "toggle") await setSettings({ blockTrackers: !!c.on });
  if (c.action === "block") await setSettings({ customBlocks: [...new Set([...s.customBlocks, ...c.domains.filter((d) => DOMAIN.test(d))])] });
  if (c.action === "unblock") await setSettings({ customBlocks: s.customBlocks.filter((d) => !c.domains.includes(d)) });
  if (c.action === "pause" && (DOMAIN.test(c.site) || /^\d{1,3}(\.\d{1,3}){3}$/.test(c.site))) await setSettings({ allowlist: [...new Set([...s.allowlist, c.site])] });
  if (c.action === "resume") await setSettings({ allowlist: s.allowlist.filter((d) => d !== c.site) });
  return syncRules(await getSettings()); // apply now; don't wait for the storage event
}

export default defineBackground({
  type: "module",
  main() {
    browser.webRequest.onBeforeRequest.addListener(
      (d) => {
        if (!isWebUrl(d.url) || d.tabId < 0) return undefined;
        pending.set(d.requestId, { ts: Date.now(), reqBytes: bodySize(d) });
        return undefined;
      },
      { urls: ["<all_urls>"] },
      ["requestBody"],
    );

    const finish = (d: { requestId: string; url: string; method: string; initiator?: string; ip?: string; tabId: number; responseHeaders?: { name: string; value?: string }[]; error?: string }) => {
      const p = pending.get(d.requestId);
      pending.delete(d.requestId);
      if (!p || !isWebUrl(d.url)) return;
      const url = new URL(d.url);
      const site = registrable(hostOf(d.initiator) || url.hostname);
      const { tracker, company } = lookup(url.hostname);
      const len = Number(d.responseHeaders?.find((h) => h.name.toLowerCase() === "content-length")?.value ?? 0) || 0;
      const flow: ExtFlow = {
        id: `ext-${d.requestId}-${p.ts}`,
        ts: p.ts,
        app: site,
        host: url.hostname,
        method: d.method,
        path: url.pathname,
        ip: d.ip ?? "",
        country: "ZZ", // no GeoIP in the browser; the agent fills this when bridged
        company,
        tracker,
        decrypted: true, // seen before TLS: pinning is irrelevant here
        pii: [],
        severity: 0,
        tcf: null,
        bytes: p.reqBytes + len,
        thirdParty: registrable(url.hostname) !== site,
        source: "extension",
        initiator: site,
      };
      appendFlow(flow);
      if (flow.thirdParty && d.tabId >= 0 && url.search) void recordSentIds(d.tabId, url);
      if (d.tabId >= 0) {
        void bumpTab(d.tabId, site, (t) => {
          t.requests++;
          if (flow.thirdParty) {
            const dom = registrable(url.hostname);
            if (!t.domains?.includes(dom)) t.domains = [...(t.domains ?? []), dom].slice(-100);
          }
          if (tracker && flow.thirdParty) {
            t.trackers++;
            const c = company || tracker.name;
            t.companies[c] = (t.companies[c] ?? 0) + 1;
          }
        });
      }
    };

    // New top-level navigation: start the tab's counters fresh.
    browser.tabs.onUpdated.addListener((tabId, info) => {
      if (info.url) void resetTab(tabId);
    });
    browser.tabs.onRemoved.addListener((tabId) => void resetTab(tabId));
    browser.tabs.onUpdated.addListener((tabId, info, tab) => {
      if (info.status === "complete" && isWebUrl(tab.url)) void runAudit(tabId);
    });

    browser.runtime.onMessage.addListener((msg: unknown, sender) => {
      const m = msg as { type?: string; flagged?: boolean; surfaces?: number; frame?: string; url?: string; method?: string; body?: string; host?: string; field?: string; via?: string; tabId?: number };
      // From our own extension pages (popup/dashboard), identified by their extension URL.
      const fromOwnPage = sender.id === browser.runtime.id && (sender.url ?? "").startsWith(browser.runtime.getURL("/"));
      if (m.type === "audit_request" && fromOwnPage && Number.isInteger(m.tabId)) {
        return runAudit(m.tabId!);
      }
      if (fromOwnPage && m.type === "patronus") return patronus(msg as PatronusCmd);
      const tabId = sender.tab?.id;
      if (tabId === undefined || tabId < 0 || !sender.tab?.url) return undefined;
      const site = registrable(hostOf(sender.tab.url));
      if (m.type === "net" && typeof m.url === "string" && isWebUrl(m.url)) {
        void handleBody(tabId, site, m.url, m.method ?? "GET", typeof m.body === "string" ? m.body : "");
        return undefined;
      }
      if (m.type === "harvest" && typeof m.host === "string") {
        const field = ["email", "phone", "password", "card", "text"].includes(String(m.field)) ? String(m.field) : "text";
        const via = ["plain", "url-encoded", "base64", "sha256"].includes(String(m.via)) ? String(m.via) : "plain";
        void bumpTab(tabId, site, (t) => {
          t.harvest = [...(t.harvest ?? []), { host: m.host!.slice(0, 255), field, via, ts: Date.now() }].slice(-20);
        });
        return undefined;
      }
      if (m.type === "fingerprint") {
        void bumpTab(tabId, site, (t) => {
          t.fingerprint = Math.max(t.fingerprint, Number(m.surfaces) || 0);
          if (m.flagged) t.fpFlagged = true;
          if (m.flagged && m.frame && !t.fpFrames?.includes(m.frame)) t.fpFrames = [...(t.fpFrames ?? []), m.frame].slice(0, 10);
        });
      }
      return undefined;
    });

    browser.webRequest.onCompleted.addListener(finish, { urls: ["<all_urls>"] }, ["responseHeaders"]);
    browser.webRequest.onErrorOccurred.addListener(
      (d) => {
        if (d.error === "net::ERR_BLOCKED_BY_CLIENT" && d.tabId >= 0) {
          pending.delete(d.requestId);
          const site = registrable(hostOf(d.initiator) || hostOf(d.url));
          void bumpTab(d.tabId, site, (t) => {
            t.blocked++;
          });
          return;
        }
        finish({ ...d, responseHeaders: [] });
      },
      { urls: ["<all_urls>"] },
    );

    // Keep DNR rules in sync with settings (install, browser start, any settings change).
    const resync = () => void getSettings().then(syncRules).catch(() => undefined);
    browser.runtime.onInstalled.addListener(resync);
    browser.runtime.onStartup.addListener(resync);
    browser.storage.local.onChanged.addListener((changes) => {
      if (changes.settings) resync();
    });
  },
});
