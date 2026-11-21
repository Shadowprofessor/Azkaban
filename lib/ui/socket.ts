"use client";

import { AGENT_WS_URL, type AgentToUi, type UiToAgent } from "@/lib/live/protocol";
import { suppressToastsFor, useAgent } from "./store";

const FLUSH_MS = 100;
const MAX_BACKOFF_MS = 5000;

/**
 * Single WebSocket to the local agent. Messages are buffered and flushed into
 * the store every 100ms (never one setState per message). Reconnects with
 * exponential backoff capped at 5s. Only ever talks to 127.0.0.1.
 */
class AgentSocket {
  private ws: WebSocket | null = null;
  private buffer: AgentToUi[] = [];
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private attempt = 0;
  private stopped = true;

  start() {
    if (!this.stopped) return;
    this.stopped = false;
    this.flushTimer = setInterval(() => this.flush(), FLUSH_MS);
    this.connect();
  }

  stop() {
    this.stopped = true;
    if (this.flushTimer) clearInterval(this.flushTimer);
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.ws?.close();
    this.ws = null;
  }

  send(cmd: UiToAgent): boolean {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(cmd));
      return true;
    }
    useAgent.getState().pushToast({ level: "error", title: "Agent offline — command not sent." });
    return false;
  }

  private connect() {
    if (this.stopped) return;
    useAgent.getState().setConn("connecting");
    let ws: WebSocket;
    try {
      ws = new WebSocket(AGENT_WS_URL);
    } catch {
      this.scheduleRetry();
      return;
    }
    this.ws = ws;
    ws.onopen = () => {
      this.attempt = 0;
      suppressToastsFor(1500);
      useAgent.getState().setConn("open");
    };
    ws.onmessage = (ev) => {
      try {
        const msg = JSON.parse(typeof ev.data === "string" ? ev.data : "") as AgentToUi;
        if (msg && typeof msg.type === "string") this.buffer.push(msg);
      } catch {
        /* ignore malformed frames */
      }
    };
    ws.onclose = () => {
      if (this.ws === ws) this.ws = null;
      this.flush();
      useAgent.getState().setConn("offline");
      this.scheduleRetry();
    };
    ws.onerror = () => ws.close();
  }

  private scheduleRetry() {
    if (this.stopped) return;
    const delay = Math.min(MAX_BACKOFF_MS, 500 * 2 ** this.attempt++);
    this.retryTimer = setTimeout(() => this.connect(), delay);
  }

  private flush() {
    if (!this.buffer.length) return;
    const batch = this.buffer;
    this.buffer = [];
    useAgent.getState().ingest(batch);
  }
}

export const agentSocket = new AgentSocket();
export const sendCommand = (cmd: UiToAgent) => agentSocket.send(cmd);
