import { create } from 'zustand';
import { MAX_FLOWS } from './schema';

function readLinkedApps() {
  try {
    const value = JSON.parse(sessionStorage.getItem('ghostprint-linked-apps') || '[]');
    return Array.isArray(value) ? value.filter((item) => typeof item === 'string') : [];
  } catch {
    return [];
  }
}

export const useGhostStore = create((set) => ({
  consent: sessionStorage.getItem('ghostprint-consent') === 'accepted',
  agent: { connected: false, known: false, capturing: false, device: 'laptop', version: '' },
  flows: [],
  verdicts: {},
  score: null,
  filters: { app: '', piiType: '', minSeverity: 0 },
  selectedFlowId: null,
  baseline: null,
  blocklist: null,
  evidence: null,
  linkedApps: readLinkedApps(),
  error: '',
  setConsent: (consent) => { if (consent) sessionStorage.setItem('ghostprint-consent', 'accepted'); else sessionStorage.removeItem('ghostprint-consent'); set({ consent }); },
  setAgent: (agent) => set((state) => ({ agent: { ...state.agent, ...agent } })),
  addFlows: (newFlows) => set((state) => ({ flows: [...newFlows, ...state.flows].slice(0, MAX_FLOWS) })),
  setVerdict: (verdict) => set((state) => ({ verdicts: { ...state.verdicts, [verdict.flowId]: verdict } })),
  setScore: (score) => set({ score }),
  setFilter: (key, value) => set((state) => ({ filters: { ...state.filters, [key]: value } })),
  selectFlow: (selectedFlowId) => set({ selectedFlowId }),
  setBaseline: (baseline) => set({ baseline }),
  setBlocklist: (blocklist) => set({ blocklist }),
  setEvidence: (evidence) => set({ evidence }),
  setLinkedApps: (linkedApps) => { sessionStorage.setItem('ghostprint-linked-apps', JSON.stringify(linkedApps)); set({ linkedApps }); },
  setError: (error) => set({ error }),
  clearError: () => set({ error: '' }),
}));
