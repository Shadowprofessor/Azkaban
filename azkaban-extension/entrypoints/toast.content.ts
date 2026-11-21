// On-page alerts for high-severity findings.
//
// Rendered inside a shadow root so the page's CSS cannot restyle the warning and the
// warning cannot restyle the page. Everything lives in one host element with a very high
// z-index; toasts stack rather than overlap, and each one is dismissible.
//
// Top frame only: an ad iframe should not be able to draw a warning banner, and the
// background only ever addresses the top frame anyway.
import { defineContentScript } from "wxt/utils/define-content-script";
import { browser } from "wxt/browser";
import type { Severity } from "../lib/alerts";

const HOST_ID = "azkaban-toasts";
const LIFETIME_MS = 5000;

const CSS = `
:host { all: initial; }
.stack {
  position: fixed; bottom: 20px; right: 20px; z-index: 2147483647;
  display: flex; flex-direction: column; gap: 8px; align-items: flex-end;
  font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
  pointer-events: none;
}
.toast {
  pointer-events: auto; cursor: pointer; max-width: 360px;
  padding: 11px 14px; border-radius: 8px; color: #fff; font-size: 14px; line-height: 1.4;
  box-shadow: 0 4px 14px rgba(0, 0, 0, 0.35);
  animation: azk-in 240ms cubic-bezier(0.2, 0.8, 0.2, 1);
  display: flex; gap: 9px; align-items: flex-start;
}
.toast.out { animation: azk-out 200ms ease-in forwards; }
.warning { background: #d97706; }
.critical { background: #dc2626; }
.mark { font-size: 15px; line-height: 1.25; flex: none; }
.text { flex: 1; }
.hint { display: block; margin-top: 3px; font-size: 11px; opacity: 0.8; }
@keyframes azk-in { from { opacity: 0; transform: translateX(16px); } to { opacity: 1; transform: none; } }
@keyframes azk-out { to { opacity: 0; transform: translateX(16px); } }
@media (prefers-reduced-motion: reduce) {
  .toast, .toast.out { animation: none; }
}
`;

let stack: HTMLElement | null = null;

/** Create the shadow host lazily; at document_start there may be no body yet. */
function ensureStack(): HTMLElement | null {
  if (stack?.isConnected) return stack;
  const parent = document.body ?? document.documentElement;
  if (!parent) return null;
  document.getElementById(HOST_ID)?.remove();
  const host = document.createElement("div");
  host.id = HOST_ID;
  // The host itself must not affect layout.
  host.style.cssText = "all:initial;position:static";
  const root = host.attachShadow({ mode: "closed" });
  const style = document.createElement("style");
  style.textContent = CSS;
  const el = document.createElement("div");
  el.className = "stack";
  root.append(style, el);
  parent.appendChild(host);
  stack = el;
  return el;
}

function dismiss(toast: HTMLElement): void {
  if (toast.classList.contains("out")) return;
  toast.classList.add("out");
  // Fall back to a timer in case the animation never fires (reduced motion).
  const done = () => toast.remove();
  toast.addEventListener("animationend", done, { once: true });
  setTimeout(done, 300);
}

export function showToast(message: string, severity: Severity): void {
  const host = ensureStack();
  if (!host) return;
  const toast = document.createElement("div");
  toast.className = `toast ${severity === "critical" ? "critical" : "warning"}`;
  toast.setAttribute("role", severity === "critical" ? "alert" : "status");
  const mark = document.createElement("span");
  mark.className = "mark";
  mark.textContent = severity === "critical" ? "\u{1F6E1}" : "⚠";
  const text = document.createElement("span");
  text.className = "text";
  // textContent, never innerHTML: the domain in the message comes from page traffic.
  text.textContent = message;
  const hint = document.createElement("span");
  hint.className = "hint";
  hint.textContent = "Azkaban · click to dismiss";
  text.appendChild(hint);
  toast.append(mark, text);
  toast.addEventListener("click", () => dismiss(toast));
  host.appendChild(toast);
  setTimeout(() => dismiss(toast), LIFETIME_MS);
}

export default defineContentScript({
  matches: ["<all_urls>"],
  runAt: "document_idle",
  allFrames: false, // top frame only: a nested ad frame must not be able to draw warnings
  main() {
    browser.runtime.onMessage.addListener((msg: unknown) => {
      const m = msg as { type?: string; message?: string; severity?: string };
      if (m?.type !== "azkaban-toast" || typeof m.message !== "string") return undefined;
      showToast(m.message.slice(0, 300), m.severity === "critical" ? "critical" : "warning");
      return undefined;
    });
  },
});
