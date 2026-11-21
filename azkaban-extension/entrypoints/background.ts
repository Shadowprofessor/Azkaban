import { defineBackground } from "wxt/utils/define-background";
import { browser } from "wxt/browser";
import { hostOf, isWebUrl, registrable } from "../lib/domain";
import { appendFlow, attachFindings, getSettings, type ExtFlow } from "../lib/store";
import { scan, toHits } from "../lib/pii";
import { lookup } from "../lib/trackers";
import { bumpTab, resetTab } from "../lib/tabs";

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
      if (d.tabId >= 0) {
        void bumpTab(d.tabId, site, (t) => {
          t.requests++;
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

    browser.runtime.onMessage.addListener((msg: unknown, sender) => {
      const m = msg as { type?: string; flagged?: boolean; surfaces?: number; frame?: string; url?: string; method?: string; body?: string; host?: string; field?: string; via?: string };
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
    browser.webRequest.onErrorOccurred.addListener((d) => finish({ ...d, responseHeaders: [] }), { urls: ["<all_urls>"] });
  },
});
