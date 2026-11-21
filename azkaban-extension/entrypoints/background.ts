import { defineBackground } from "wxt/utils/define-background";
import { browser } from "wxt/browser";
import { hostOf, isWebUrl, registrable } from "../lib/domain";
import { appendFlow, type ExtFlow } from "../lib/store";
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
      const m = msg as { type?: string; flagged?: boolean; surfaces?: number; frame?: string };
      const tabId = sender.tab?.id;
      if (tabId === undefined || tabId < 0 || !sender.tab?.url) return undefined;
      const site = registrable(hostOf(sender.tab.url));
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
