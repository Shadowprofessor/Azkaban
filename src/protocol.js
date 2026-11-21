// Frozen local-agent WebSocket protocol from the GhostPrint frontend PRD.
export const OUTBOUND = {
  start: (device) => ({ type: 'start', device }),
  stop: () => ({ type: 'stop' }),
  analyze: (flowId) => ({ type: 'analyze', flowId }),
  blocklist: (format) => ({ type: 'blocklist', format }),
  exportEvidence: () => ({ type: 'export_evidence' }),
};

export const INBOUND_TYPES = ['status', 'flow', 'verdict', 'score', 'blocklist', 'evidence', 'error'];
