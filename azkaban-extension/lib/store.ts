// Persistence for the MV3 service worker. The SW is ephemeral, so nothing important lives
// in module state: flows go to storage.session (wiped when the browser closes), settings and
// counters to storage.local. Raw request bodies are NEVER stored — only redacted findings.
import { browser } from "wxt/browser";
import type { Flow } from "../../lib/schema";

export const RING_MAX = 1000;

export interface ExtFlow extends Flow {
  thirdParty: boolean;
  source: "extension";
  initiator: string; // site eTLD+1 that caused the request
  findings?: { kind: string; detail: string }[];
  // Inspector fields (extension-only, all optional so older stored flows still load).
  tabId?: number;
  status?: number; // HTTP status, 0 when the request failed or was blocked
  rtype?: string; // webRequest resource type: script, xmlhttprequest, image, ...
  ms?: number; // request start -> completion
  scheme?: string; // http / https / ws / wss
  queryKeys?: string[]; // parameter NAMES only; values can carry identifiers
  cookieSent?: boolean; // a Cookie header went out with the request
  setCookies?: string[]; // cookie NAMES the response tried to set (values never kept)
  blocked?: "request" | "cookies"; // Patronus blocked the request, or stripped its cookies
  error?: string;
}

export interface Settings {
  muted: boolean;
  agentBridge: boolean;
  blockTrackers: boolean;
  allowlist: string[]; // sites where blocking is paused ("site broken? pause here")
  customBlocks: string[]; // extra domains blocked by the user
  knownHashes: string[]; // sha256 of the user's own identifiers (raw values never stored)
  cookieBlocks: string[]; // domains whose cookies are stripped both ways and purged
  blockThirdPartyCookies: boolean; // strip cookies on every third-party request
}

export const DEFAULT_SETTINGS: Settings = {
  muted: false,
  agentBridge: true,
  blockTrackers: false,
  allowlist: [],
  customBlocks: [],
  knownHashes: [],
  cookieBlocks: [],
  blockThirdPartyCookies: false,
};

export async function getSettings(): Promise<Settings> {
  const r = await browser.storage.local.get("settings");
  return { ...DEFAULT_SETTINGS, ...((r.settings as Partial<Settings>) ?? {}) };
}

export async function setSettings(patch: Partial<Settings>): Promise<Settings> {
  const next = { ...(await getSettings()), ...patch };
  await browser.storage.local.set({ settings: next });
  return next;
}

export async function getFlows(): Promise<ExtFlow[]> {
  const r = await browser.storage.session.get("flows");
  return (r.flows as ExtFlow[]) ?? [];
}

// All read-modify-write on the flow ring goes through one chain, so concurrent events
// (webRequest flush, body findings, updates) can never overwrite each other.
let lock: Promise<unknown> = Promise.resolve();
function locked<T>(fn: () => Promise<T>): Promise<T> {
  const run = lock.then(fn, fn);
  lock = run.catch(() => undefined);
  return run;
}

// Writes are batched: a short-lived queue flushed every 300ms. If the SW is killed in that
// window, at most those few flows are lost — acceptable for a live view.
let queue: ExtFlow[] = [];
let timer: ReturnType<typeof setTimeout> | null = null;

export function appendFlow(f: ExtFlow): void {
  queue.push(f);
  if (!timer) timer = setTimeout(flush, 300);
}

function flush(): Promise<void> {
  timer = null;
  return locked(flushUnlocked);
}

async function flushUnlocked(): Promise<void> {
  if (!queue.length) return;
  const batch = queue;
  queue = [];
  let flows = await getFlows();
  // A body finding can arrive before its request completes, and is then recorded on its own
  // (attachFindings). When the request lands, fold that placeholder into it: one request,
  // one row, with the findings attached.
  for (const f of batch) {
    const i = flows.slice(0, 200).findIndex(
      (o) => o.id.startsWith("ext-body-") && o.host === f.host && o.path === f.path && Math.abs(o.ts - f.ts) < 15_000,
    );
    if (i < 0) continue;
    const body = flows[i]!;
    f.pii = body.pii;
    f.severity = Math.max(f.severity, body.severity);
    if (body.findings?.length) f.findings = body.findings;
    flows = flows.filter((_, j) => j !== i);
  }
  const next = [...batch.reverse(), ...flows].slice(0, RING_MAX);
  await browser.storage.session.set({ flows: next });
}

export function updateFlow(id: string, patch: Partial<ExtFlow>): Promise<void> {
  return locked(async () => {
  await flushUnlocked();
  const flows = await getFlows();
  const i = flows.findIndex((f) => f.id === id);
  if (i >= 0) {
    flows[i] = { ...flows[i], ...patch } as ExtFlow;
    await browser.storage.session.set({ flows });
  }
  });
}

/** Attach redacted findings to the matching captured request, or record a new flow. */
export function attachFindings(base: ExtFlow, maxAgeMs = 15_000): Promise<void> {
  return locked(async () => {
  await flushUnlocked();
  const flows = await getFlows();
  const i = flows.slice(0, 200).findIndex(
    (f) => f.host === base.host && f.path === base.path && !f.pii.length && Math.abs(f.ts - base.ts) < maxAgeMs,
  );
  const hit = i >= 0 ? flows[i] : undefined;
  if (hit) flows[i] = { ...hit, pii: base.pii, severity: Math.max(hit.severity, base.severity), findings: base.findings };
  else flows.unshift(base);
  await browser.storage.session.set({ flows: flows.slice(0, RING_MAX) });
  });
}

export async function wipeAll(): Promise<void> {
  queue = [];
  await browser.storage.session.clear();
  await browser.storage.local.clear();
}
