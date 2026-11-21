// FROZEN CONTRACT — WebSocket protocol between azkaban-agent and the dashboard.
// Agent listens on ws://127.0.0.1:8787 (loopback only).
// Every message is a JSON object with a `type` discriminator.

import type { Flow, Verdict, Score } from '../schema';

export const AGENT_WS_URL = 'ws://127.0.0.1:8787';

// ---------------------------------------------------------------- agent -> UI

export interface StatusMsg {
  type: 'status';
  capturing: boolean;
  /** 'live' | 'replay' | 'idle' */
  mode: 'live' | 'replay' | 'idle';
  proxy: string; // e.g. "127.0.0.1:8080"
  flows: number; // flows seen this session
  engines: { llm: boolean; rag: boolean; model: boolean; geo: boolean };
  version: string;
}

export interface FlowMsg {
  type: 'flow';
  flow: Flow;
}

export interface VerdictMsg {
  type: 'verdict';
  verdict: Verdict;
}

export interface ScoreMsg {
  type: 'score';
  score: Score;
  /** Remediation ranked by marginal score reduction (largest first). */
  remediation: { target: string; kind: 'host' | 'company'; reduction: number }[];
}

export interface BlocklistMsg {
  type: 'blocklist';
  hosts: string[];
  formats: { hosts: string; pihole: string; nextdns: string; pf: string };
  applied: boolean;
  /** Present after apply-and-recheck: leaks before vs after. */
  recheck: { baseline: number; current: number; delta: number } | null;
}

export interface EvidenceMsg {
  type: 'evidence';
  path: string;
  rootHash: string;
  entries: number;
}

/**
 * ADDITIVE (v1.1): findings that span many flows. Safe to ignore.
 * `key` is stable per finding — replace the previous insight with the same key.
 */
export interface InsightMsg {
  type: 'insight';
  key: string;
  kind: 'idle_beacons' | 'cross_app' | 'hashed_pii' | 'dns_bypass' | 'bandwidth' | 'honeytoken' | 'recheck';
  level: 'info' | 'warn' | 'critical';
  title: string;
  detail: string;
  data: Record<string, unknown>;
}

export interface ErrorMsg {
  type: 'error';
  code: string;
  message: string;
}

export type AgentToUi =
  | StatusMsg
  | FlowMsg
  | VerdictMsg
  | ScoreMsg
  | BlocklistMsg
  | EvidenceMsg
  | InsightMsg
  | ErrorMsg;

// ---------------------------------------------------------------- UI -> agent

export interface StartCmd { type: 'start' }
export interface StopCmd { type: 'stop' }
export interface AnalyzeCmd { type: 'analyze'; flowId: string }
export interface BlocklistCmd {
  type: 'blocklist';
  /** 'generate' builds rules; 'apply' enforces them in-proxy and starts a recheck. */
  action: 'generate' | 'apply' | 'clear';
}
export interface ExportEvidenceCmd { type: 'export_evidence' }

export type UiToAgent =
  | StartCmd
  | StopCmd
  | AnalyzeCmd
  | BlocklistCmd
  | ExportEvidenceCmd;
