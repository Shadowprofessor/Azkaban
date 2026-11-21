"use client";

import { create } from "zustand";
import type { Flow, Score, Verdict } from "@/lib/schema";
import type {
  AgentToUi,
  BlocklistMsg,
  EvidenceMsg,
  InsightMsg,
  ScoreMsg,
  StatusMsg,
} from "@/lib/live/protocol";

export const MAX_FLOWS = 2000;
export type Conn = "connecting" | "open" | "offline";

export interface Toast {
  id: number;
  level: InsightMsg["level"] | "error";
  title: string;
  detail?: string;
}

export interface Filters {
  text: string;
  app: string | null;
  company: string | null;
  piiType: string | null;
  minSeverity: number;
  onlyPinned: boolean;
}

const EMPTY_FILTERS: Filters = { text: "", app: null, company: null, piiType: null, minSeverity: 0, onlyPinned: false };

interface State {
  conn: Conn;
  lastMessageAt: number | null;
  status: StatusMsg | null;
  flows: Flow[]; // newest first, capped
  flowById: Record<string, Flow>;
  verdicts: Record<string, Verdict>;
  pendingAnalyze: Record<string, number>;
  score: Score | null;
  remediation: ScoreMsg["remediation"];
  blocklist: BlocklistMsg | null;
  insights: Record<string, InsightMsg>;
  insightOrder: string[]; // newest first
  evidence: EvidenceMsg | null;
  evidencePending: boolean;
  errors: { code: string; message: string; at: number }[];
  toasts: Toast[];
  selectedFlowId: string | null;
  filters: Filters;
  ingest: (batch: AgentToUi[]) => void;
  setConn: (c: Conn) => void;
  select: (id: string | null) => void;
  setFilters: (f: Partial<Filters>) => void;
  resetFilters: () => void;
  dismissToast: (id: number) => void;
  pushToast: (t: Omit<Toast, "id">) => void;
  markAnalyze: (flowId: string) => void;
  setEvidencePending: (v: boolean) => void;
}

let toastSeq = 0;
// Rate-limit toasts: at most one per insight key per 30s, and max 3 on screen.
const lastToastByKey = new Map<string, number>();
const TOAST_KEY_COOLDOWN_MS = 30_000;
const TOAST_LEVELS = new Set(["warn", "critical"]);

export const useAgent = create<State>((set, get) => ({
  conn: "connecting",
  lastMessageAt: null,
  status: null,
  flows: [],
  flowById: {},
  verdicts: {},
  pendingAnalyze: {},
  score: null,
  remediation: [],
  blocklist: null,
  insights: {},
  insightOrder: [],
  evidence: null,
  evidencePending: false,
  errors: [],
  toasts: [],
  selectedFlowId: null,
  filters: EMPTY_FILTERS,

  setConn: (conn) => set({ conn }),
  select: (selectedFlowId) => set({ selectedFlowId }),
  setFilters: (f) => set({ filters: { ...get().filters, ...f } }),
  resetFilters: () => set({ filters: EMPTY_FILTERS }),
  dismissToast: (id) => set({ toasts: get().toasts.filter((t) => t.id !== id) }),
  pushToast: (t) => set({ toasts: [...get().toasts, { ...t, id: ++toastSeq }].slice(-3) }),
  markAnalyze: (flowId) => set({ pendingAnalyze: { ...get().pendingAnalyze, [flowId]: Date.now() } }),
  setEvidencePending: (evidencePending) => set({ evidencePending }),

  ingest: (batch) => {
    if (!batch.length) return;
    const s = get();
    let flows: Flow[] | null = null;
    let flowById = s.flowById;
    let verdicts = s.verdicts;
    let pendingAnalyze = s.pendingAnalyze;
    let insights = s.insights;
    let insightOrder = s.insightOrder;
    let toasts = s.toasts;
    const patch: Partial<State> = { lastMessageAt: Date.now() };
    const newFlows: Flow[] = [];

    for (const m of batch) {
      switch (m.type) {
        case "status":
          patch.status = m;
          break;
        case "flow":
          if (!flowById[m.flow.id]) newFlows.push(m.flow);
          break;
        case "verdict":
          if (verdicts === s.verdicts) verdicts = { ...verdicts };
          verdicts[m.verdict.flowId] = m.verdict;
          if (pendingAnalyze[m.verdict.flowId]) {
            pendingAnalyze = { ...pendingAnalyze };
            delete pendingAnalyze[m.verdict.flowId];
          }
          break;
        case "score":
          patch.score = m.score;
          patch.remediation = m.remediation;
          break;
        case "blocklist":
          patch.blocklist = m;
          break;
        case "evidence":
          patch.evidence = m;
          patch.evidencePending = false;
          break;
        case "insight": {
          if (insights === s.insights) insights = { ...insights };
          const isNew = !insights[m.key];
          insights[m.key] = m;
          insightOrder = [m.key, ...insightOrder.filter((k) => k !== m.key)].slice(0, 200);
          const now = Date.now();
          const last = lastToastByKey.get(m.key) ?? 0;
          if (TOAST_LEVELS.has(m.level) && (isNew || now - last > TOAST_KEY_COOLDOWN_MS)) {
            lastToastByKey.set(m.key, now);
            toasts = [...toasts, { id: ++toastSeq, level: m.level, title: m.title, detail: m.detail }].slice(-3);
          }
          break;
        }
        case "error":
          patch.errors = [{ code: m.code, message: m.message, at: Date.now() }, ...(patch.errors ?? s.errors)].slice(0, 20);
          if (m.code === "command_failed" || m.code === "llm_unavailable") {
            toasts = [...toasts, { id: ++toastSeq, level: "error" as const, title: m.message }].slice(-3);
          }
          break;
      }
    }

    if (newFlows.length) {
      flowById = { ...flowById };
      for (const f of newFlows) flowById[f.id] = f;
      flows = [...newFlows.reverse(), ...s.flows];
      if (flows.length > MAX_FLOWS) {
        for (const f of flows.slice(MAX_FLOWS)) delete flowById[f.id];
        flows = flows.slice(0, MAX_FLOWS);
      }
      patch.flows = flows;
      patch.flowById = flowById;
    }
    if (verdicts !== s.verdicts) patch.verdicts = verdicts;
    if (pendingAnalyze !== s.pendingAnalyze) patch.pendingAnalyze = pendingAnalyze;
    if (insights !== s.insights) {
      patch.insights = insights;
      patch.insightOrder = insightOrder;
    }
    if (toasts !== s.toasts) patch.toasts = toasts;
    set(patch);
  },
}));

export function applyFilters(flows: Flow[], f: Filters): Flow[] {
  const q = f.text.trim().toLowerCase();
  if (!q && !f.app && !f.company && !f.piiType && !f.minSeverity && !f.onlyPinned) return flows;
  return flows.filter(
    (x) =>
      (!q || x.host.toLowerCase().includes(q) || x.app.toLowerCase().includes(q) || (x.company ?? "").toLowerCase().includes(q)) &&
      (!f.app || x.app === f.app) &&
      (!f.company || (x.company || x.host) === f.company) &&
      (!f.piiType || x.pii.some((p) => p.type === f.piiType)) &&
      x.severity >= f.minSeverity &&
      (!f.onlyPinned || !x.decrypted),
  );
}
