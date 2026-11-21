// Isolated-world bridge: receives MAIN-world probe events, validates them (the page can
// forge window messages, so nothing here is trusted beyond its own tab), and relays to the
// background service worker.
import { defineContentScript } from "wxt/utils/define-content-script";
import { browser } from "wxt/browser";

const CHANNEL = "__azkaban_probe__";

export default defineContentScript({
  matches: ["<all_urls>"],
  runAt: "document_start",
  allFrames: true,
  main() {
    window.addEventListener("message", (ev) => {
      try {
        if (ev.source !== window || !ev.data || ev.data[CHANNEL] !== true) return;
        const d = ev.data as Record<string, unknown>;
        if (d.kind === "net" && typeof d.url === "string" && typeof d.body === "string") {
          void browser.runtime
            .sendMessage({ type: "net", url: d.url.slice(0, 4096), method: String(d.method ?? "GET").slice(0, 16), body: d.body.slice(0, 16384) })
            .catch(() => undefined);
          return;
        }
        if (d.kind === "fingerprint") {
          const surfaces = Math.max(0, Math.min(6, Number(d.surfaces) || 0));
          void browser.runtime
            .sendMessage({ type: "fingerprint", flagged: d.flagged === true, surfaces, frame: location.hostname })
            .catch(() => undefined);
        }
      } catch {
        /* never break the page */
      }
    });
  },
});
