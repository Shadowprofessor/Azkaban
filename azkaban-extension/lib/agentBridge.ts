// Optional link to the local Azkaban agent.
//
// The extension is useful on its own and must stay useful when the agent is not running,
// so every failure here is silent and non-fatal: findings are always recorded locally
// first, and the bridge is a best-effort copy to the agent on top of that.
//
// Direction: the extension PRODUCES. It sends findings and site scores and receives only a
// handshake ack. It never asks the agent for flows. The agent enforces that too
// (azkaban_agent/extbridge.py), and refuses an extension origin on the dashboard path.
//
// MV3: the service worker is evicted when idle, which takes any setTimeout with it. The
// reconnect therefore runs off browser.alarms, which survive eviction and wake the worker.
import { browser } from "wxt/browser";
import { getSettings } from "./store";
import { detectionMsg, helloMsg, siteScoreMsg } from "./bridgeProtocol";
import type { SiteScore } from "./scoring";

export const AGENT_WS_URL = "ws://127.0.0.1:8787/ws/extension";
export const RECONNECT_ALARM = "azkaban-agent-reconnect";
/** browser.alarms will not go below one minute. */
const RECONNECT_MINUTES = 1;
const STATE_KEY = "bridge";
const QUEUE_KEY = "bridgeQueue";
/** Findings held while the agent is down. Oldest dropped first when full. */
export const QUEUE_MAX = 500;

export type BridgeStatus = "connected" | "standalone";

export interface BridgeState {
  status: BridgeStatus;
  /** How many findings are waiting for the agent to come back. */
  queued: number;
  agentVersion: string;
  /** Engine flags from the agent's ack, so the popup can show what is actually running. */
  engines: Record<string, boolean>;
  sent: number;
  lastError: string;
  since: number;
}

const BLANK: BridgeState = {
  status: "standalone", agentVersion: "", engines: {}, sent: 0, lastError: "", since: 0,
  queued: 0,
};

export async function getBridgeState(): Promise<BridgeState> {
  const r = await browser.storage.session.get(STATE_KEY);
  return { ...BLANK, ...((r[STATE_KEY] as Partial<BridgeState>) ?? {}) };
}

async function patchState(patch: Partial<BridgeState>): Promise<void> {
  const next = { ...(await getBridgeState()), ...patch };
  await browser.storage.session.set({ [STATE_KEY]: next });
}

/**
 * Findings recorded while the agent was not running.
 *
 * storage.local, not session: the point is that closing the browser does not lose them.
 * Only the same already-redacted detections that would have been sent live are queued, so
 * nothing is stored here that would not have been sent anyway.
 */
async function readQueue(): Promise<unknown[]> {
  const r = await browser.storage.local.get(QUEUE_KEY);
  const q = r[QUEUE_KEY];
  return Array.isArray(q) ? q : [];
}

async function writeQueue(items: unknown[]): Promise<void> {
  await browser.storage.local.set({ [QUEUE_KEY]: items.slice(-QUEUE_MAX) });
  await patchState({ queued: Math.min(items.length, QUEUE_MAX) });
}

export async function queueSize(): Promise<number> {
  return (await readQueue()).length;
}

export interface BrowserDetection {
  kind: "unknown_tracker" | "fingerprinting" | "harvest" | "hashed_pii" | "third_party_volume";
  host: string;
  domain?: string;
  site?: string;
  /** Attributed owner, where the tracker list knows one. */
  company?: string;
  category?: string;
  confidence?: number;
  bytes?: number;
  severity?: number;
  /** Already-redacted hits only. The agent re-validates and drops anything else. */
  pii?: readonly { type: string; redacted: string; confidence: number }[];
}

class AgentBridge {
  private ws: WebSocket | null = null;
  private connecting = false;

  private get open(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  /** Connect if the user has the bridge enabled. Safe to call repeatedly. */
  async connect(): Promise<void> {
    if (this.open || this.connecting) return;
    if (!(await getSettings()).agentBridge) return;
    this.connecting = true;
    try {
      const ws = new WebSocket(AGENT_WS_URL);
      this.ws = ws;

      ws.onopen = () => {
        this.connecting = false;
        try {
          ws.send(JSON.stringify(helloMsg(browser.runtime.getManifest().version)));
        } catch {
          /* closed between open and send */
        }
      };

      ws.onmessage = (event) => {
        let msg: { type?: string; agent_version?: string; engines?: Record<string, boolean>; message?: string };
        try {
          msg = JSON.parse(String(event.data));
        } catch {
          return;
        }
        if (msg.type === "producer_ack") {
          void patchState({
            status: "connected", agentVersion: msg.agent_version ?? "",
            engines: msg.engines ?? {}, lastError: "", since: Date.now(),
          }).then(() => this.drain());      // catch the agent up on what it missed
        } else if (msg.type === "error") {
          // The agent rejected something we sent; worth surfacing, not worth dropping the link.
          void patchState({ lastError: String(msg.message ?? "").slice(0, 200) });
        }
      };

      ws.onclose = () => {
        this.connecting = false;
        this.ws = null;
        void patchState({ status: "standalone", agentVersion: "", engines: {} });
        void scheduleReconnect();
      };

      // No agent running is the normal case, not an error worth logging.
      ws.onerror = () => {
        this.connecting = false;
      };
    } catch {
      this.connecting = false;
      void scheduleReconnect();
    }
  }

  private trySend(payload: unknown, queueWhenDown = true): boolean {
    if (!this.open) {
      if (queueWhenDown) void this.enqueue(payload);
      void this.connect();
      return false;
    }
    try {
      this.ws!.send(JSON.stringify(payload));
      return true;
    } catch {
      if (queueWhenDown) void this.enqueue(payload);
      return false;
    }
  }

  private async enqueue(payload: unknown): Promise<void> {
    try {
      const q = await readQueue();
      q.push(payload);
      await writeQueue(q);
    } catch {
      /* storage full or unavailable: a dropped copy is not worth breaking the page for */
    }
  }

  /** Send everything that piled up while the agent was away, oldest first. */
  private async drain(): Promise<void> {
    let q = await readQueue();
    if (!q.length) return;
    let sent = 0;
    while (q.length && this.open) {
      const next = q[0];
      try {
        this.ws!.send(JSON.stringify(next));
      } catch {
        break;                       // socket died mid-drain: keep the rest for next time
      }
      q = q.slice(1);
      sent++;
      if (sent % 50 === 0) await writeQueue(q);   // checkpoint, so a crash loses little
    }
    await writeQueue(q);
    if (sent) {
      const s = await getBridgeState();
      await patchState({ sent: s.sent + sent });
    }
  }

  sendDetection(d: BrowserDetection): void {
    if (this.trySend(detectionMsg(d))) {
      void getBridgeState().then((s) => patchState({ sent: s.sent + 1 }));
    }
  }

  /** Site is sent as a bare hostname: a full URL would be browsing history. */
  sendSiteScore(score: SiteScore, site: string): void {
    if (!site) return;
    this.trySend(siteScoreMsg(score, site), false);   // a score is a snapshot; stale ones are noise
  }

  disconnect(): void {
    const ws = this.ws;
    this.ws = null;
    this.connecting = false;
    if (ws) {
      ws.onclose = null; // deliberate close: do not schedule a reconnect
      try {
        ws.close();
      } catch {
        /* already gone */
      }
    }
    void browser.alarms.clear(RECONNECT_ALARM);
    void patchState({ status: "standalone", agentVersion: "", engines: {} });
  }
}

export async function scheduleReconnect(): Promise<void> {
  if (!(await getSettings()).agentBridge) return;
  // Alarms survive service-worker eviction; a setTimeout would not.
  await browser.alarms.create(RECONNECT_ALARM, { delayInMinutes: RECONNECT_MINUTES });
}

export const agentBridge = new AgentBridge();
