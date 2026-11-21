// Isolated-world bridge: receives MAIN-world probe events, validates them (the page can
// forge window messages, so nothing here is trusted beyond its own tab), and relays to the
// background service worker. It also watches what the user types to catch pre-submit
// form harvesting: typed values stay in this page's memory only and are never sent anywhere.
import { defineContentScript } from "wxt/utils/define-content-script";
import { browser } from "wxt/browser";

const CHANNEL = "__azkaban_probe__";

type FieldKind = "email" | "phone" | "password" | "card" | "text";
interface Typed {
  kind: FieldKind;
  form: HTMLFormElement | null;
  variants: string[]; // raw, url-encoded, base64 — lowercased
  sha256: string;
}

async function sha256(s: string): Promise<string> {
  const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(s));
  return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

function kindOf(el: HTMLInputElement | HTMLTextAreaElement, value: string): FieldKind {
  const hint = `${el.type} ${el.name} ${el.id} ${el.autocomplete}`.toLowerCase();
  if (el.type === "password") return "password";
  if (/@/.test(value) || /mail/.test(hint)) return "email";
  if (/cc-|card/.test(hint)) return "card";
  if (/tel|phone|mobile/.test(hint) || /^\+?[\d\s()-]{8,}$/.test(value)) return "phone";
  return "text";
}

export default defineContentScript({
  matches: ["<all_urls>"],
  runAt: "document_start",
  allFrames: true,
  main() {
    const typed = new Map<Element, Typed>();
    const submitted = new WeakSet<HTMLFormElement>();
    const reported = new Set<string>();

    document.addEventListener(
      "input",
      (ev) => {
        try {
          const el = ev.target;
          if (!(el instanceof HTMLInputElement || el instanceof HTMLTextAreaElement)) return;
          const v = el.value.trim();
          if (v.length < 4 || v.length > 256) {
            typed.delete(el);
            return;
          }
          const lower = v.toLowerCase();
          let b64 = "";
          try {
            b64 = btoa(unescape(encodeURIComponent(v))).replace(/=+$/, "");
          } catch {
            /* ignore */
          }
          const entry: Typed = { kind: kindOf(el, v), form: el.form, variants: [lower, encodeURIComponent(v).toLowerCase(), b64], sha256: "" };
          typed.set(el, entry);
          void sha256(lower).then((h) => (entry.sha256 = h));
        } catch {
          /* never break the page */
        }
      },
      true,
    );
    document.addEventListener(
      "submit",
      (ev) => {
        if (ev.target instanceof HTMLFormElement) submitted.add(ev.target);
      },
      true,
    );

    const checkHarvest = (url: string, body: string) => {
      if (!typed.size) return;
      const hay = `${url}\n${body}`;
      const hayLower = hay.toLowerCase();
      let host = "";
      try {
        host = new URL(url).hostname;
      } catch {
        return;
      }
      for (const t of typed.values()) {
        if (t.form && submitted.has(t.form)) continue; // after submit, sending is expected
        const [plain = "", urlEnc = "", b64 = ""] = t.variants;
        const via = hayLower.includes(plain) ? 0 : urlEnc !== plain && hayLower.includes(urlEnc) ? 1 : b64 && hay.includes(b64) ? 2 : -1;
        const hashed = !!t.sha256 && hayLower.includes(t.sha256);
        if (via < 0 && !hashed) continue;
        const key = `${host}|${t.kind}`;
        if (reported.has(key)) continue;
        reported.add(key);
        void browser.runtime
          .sendMessage({ type: "harvest", host, field: t.kind, via: via >= 0 ? ["plain", "url-encoded", "base64"][via] : "sha256" })
          .catch(() => undefined);
      }
    };

    window.addEventListener("message", (ev) => {
      try {
        if (ev.source !== window || !ev.data || ev.data[CHANNEL] !== true) return;
        const d = ev.data as Record<string, unknown>;
        if (d.kind === "net" && typeof d.url === "string" && typeof d.body === "string") {
          const url = d.url.slice(0, 4096);
          const body = d.body.slice(0, 16384);
          checkHarvest(url, body);
          void browser.runtime
            .sendMessage({ type: "net", url, method: String(d.method ?? "GET").slice(0, 16), body })
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
