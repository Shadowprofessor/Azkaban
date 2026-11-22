// Agent protocol -> dashboard shape.
//
// The dashboard was written against the frontend PRD, which wrapped every message in a
// `data` envelope. The agent implements lib/live/protocol.ts, which is FROZEN and names
// each payload after its type: {type:'flow', flow:{...}}, {type:'verdict', verdict:{...}},
// and a flat status object. Connected directly, the dashboard's validateInbound rejected
// every message and the UI stayed empty.
//
// The agent owns the frozen contract, so the dashboard adapts. Everything is converted in
// this one file rather than by editing the components, so the contract difference stays in
// one readable place.
//
// Conversions beyond the envelope:
//   flow.ts        number (epoch ms) -> ISO string, which is what the components render
//   flow.tcf       purposes: number[] -> string[] (TCF purpose IDs are rendered as text)
//   status.version -> agentVersion
//   evidence.rootHash -> sha256
//   blocklist.formats -> content for the format the user picked

/** TCF v2 purpose names, so a purpose ID renders as something a person can read. */
export const TCF_PURPOSES = {
  1: 'Store/access information on a device',
  2: 'Select basic ads',
  3: 'Create a personalised ads profile',
  4: 'Select personalised ads',
  5: 'Create a personalised content profile',
  6: 'Select personalised content',
  7: 'Measure ad performance',
  8: 'Measure content performance',
  9: 'Apply market research',
  10: 'Develop and improve products',
  11: 'Use limited data to select content',
};

const isObject = (v) => !!v && typeof v === 'object' && !Array.isArray(v);

function normaliseFlow(flow) {
  if (!isObject(flow)) return null;
  const tcf = isObject(flow.tcf)
    ? {
        vendors: Array.isArray(flow.tcf.vendors) ? flow.tcf.vendors.length : Number(flow.tcf.vendors) || 0,
        vendorIds: Array.isArray(flow.tcf.vendors) ? flow.tcf.vendors : [],
        purposes: (Array.isArray(flow.tcf.purposes) ? flow.tcf.purposes : []).map(
          (p) => TCF_PURPOSES[p] || `Purpose ${p}`,
        ),
      }
    : null;
  return {
    ...flow,
    // Keep the raw epoch for sorting; the components want a string.
    tsMs: typeof flow.ts === 'number' ? flow.ts : Date.parse(flow.ts) || Date.now(),
    ts: typeof flow.ts === 'number' ? new Date(flow.ts).toISOString() : String(flow.ts ?? ''),
    company: flow.company || null,
    pii: Array.isArray(flow.pii) ? flow.pii : [],
    severity: Number(flow.severity) || 0,
    bytes: Number(flow.bytes) || 0,
    tcf,
    // Additive: request/response detail for the Burp-style panel, and whether this flow
    // came from the agent's durable history rather than this live session.
    traffic: isObject(flow.traffic) ? flow.traffic : null,
    requestHeaders: isObject(flow.requestHeaders) ? flow.requestHeaders : null,
    process: isObject(flow.process) ? flow.process : null,
    historical: !!flow.historical,
  };
}

/**
 * Convert one agent message into `{type, data}`, or null to ignore it.
 * `pickFormat` returns the blocklist format the user currently has selected.
 */
export function normalise(message, pickFormat = () => 'hosts') {
  if (!isObject(message) || typeof message.type !== 'string') return null;
  const t = message.type;

  if (t === 'status') {
    return {
      type: 'status',
      data: {
        capturing: !!message.capturing,
        mode: message.mode || 'idle',
        proxy: message.proxy || '',
        flows: Number(message.flows) || 0,
        engines: isObject(message.engines) ? message.engines : {},
        agentVersion: message.version || '',
        // Additive fields from the v1 agent: which reasoning engine answered.
        llmEngine: message.llmEngine || 'none',
        llmModel: message.llmModel || '',
        // Additive: idle labelling (nirmit's Idle Activity page) and the extension bridge.
        idleMonitoring: message.idleMonitoring ?? null,
        idleThresholdMs: Number(message.idleThresholdMs) || null,
        extension: isObject(message.extension) ? message.extension : null,
      },
    };
  }

  if (t === 'flow') {
    const data = normaliseFlow(message.flow);
    return data ? { type: 'flow', data } : null;
  }

  if (t === 'verdict') {
    return isObject(message.verdict) ? { type: 'verdict', data: message.verdict } : null;
  }

  if (t === 'score') {
    if (!isObject(message.score)) return null;
    return {
      type: 'score',
      data: {
        total: Number(message.score.total) || 0,
        categories: Array.isArray(message.score.categories) ? message.score.categories : [],
        remediation: Array.isArray(message.remediation) ? message.remediation : [],
      },
    };
  }

  if (t === 'blocklist') {
    const formats = isObject(message.formats) ? message.formats : {};
    const chosen = pickFormat();
    return {
      type: 'blocklist',
      data: {
        hosts: Array.isArray(message.hosts) ? message.hosts : [],
        formats,
        applied: !!message.applied,
        recheck: message.recheck ?? null,
        // What the preview pane renders.
        content: formats[chosen] ?? formats.hosts ?? '',
        format: chosen,
      },
    };
  }

  if (t === 'evidence') {
    return {
      type: 'evidence',
      data: {
        path: message.path || '',
        sha256: message.rootHash || '',
        rootHash: message.rootHash || '',
        entries: Number(message.entries) || 0,
      },
    };
  }

  if (t === 'insight') {
    // Cross-flow findings, including the retrieved remediation steps from rag/.
    return {
      type: 'insight',
      data: {
        key: message.key || '',
        kind: message.kind || '',
        level: message.level || 'info',
        title: message.title || '',
        detail: message.detail || '',
        data: isObject(message.data) ? message.data : {},
        remediation: isObject(message.data?.remediation) ? message.data.remediation : null,
        ts: Date.now(),
      },
    };
  }

  if (t === 'error') {
    return { type: 'error', data: { code: message.code || '', message: message.message || '' } };
  }

  return null;
}

/** Outbound commands, exactly as lib/live/protocol.ts defines them. */
export const COMMANDS = {
  start: () => ({ type: 'start' }),
  stop: () => ({ type: 'stop' }),
  analyze: (flowId) => ({ type: 'analyze', flowId }),
  /** The agent takes an action, not a format; the format only chooses the preview. */
  blocklist: (action = 'generate') => ({ type: 'blocklist', action }),
  exportEvidence: () => ({ type: 'export_evidence' }),
  /** Additive (nirmit): sets the inactivity window the agent uses to call a flow idle. */
  configureIdle: (inactivityMs) => ({ type: 'configure_idle', inactivityMs: Math.max(0, Number(inactivityMs) || 0) }),
};
