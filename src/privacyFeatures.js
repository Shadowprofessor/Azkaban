const hasIdleMarker = (flow) => flow.idle?.state === 'idle' && typeof flow.idle?.sessionId === 'string' && flow.idle.sessionId.length > 0;

export function deriveIdleActivity(flows) {
  const idleFlows = flows.filter(hasIdleMarker);
  const activeFlows = flows.filter((flow) => flow.idle?.state === 'active' && flow.idle?.sessionId);
  const apps = new Map();
  const destinations = new Map();
  let uploadedBytes = 0;
  let hasUploadMeasurements = false;
  let activeUploadedBytes = 0;
  let hasActiveUploadMeasurements = false;
  idleFlows.forEach((flow) => {
    const appName = flow.app || 'Unknown app';
    const app = apps.get(appName) || { app: appName, connections: 0, uploadedBytes: 0, hasUploadMeasurements: false, destinations: new Set(), signals: 0, last: flow };
    app.connections += 1;
    if (flow.host) app.destinations.add(flow.host);
    app.signals += flow.pii?.length || 0;
    if (Number.isFinite(flow.traffic?.uploadBytes) && flow.traffic.uploadBytes >= 0) {
      app.uploadedBytes += flow.traffic.uploadBytes;
      app.hasUploadMeasurements = true;
      uploadedBytes += flow.traffic.uploadBytes;
      hasUploadMeasurements = true;
    }
    if (new Date(flow.ts) > new Date(app.last.ts)) app.last = flow;
    apps.set(appName, app);
    if (flow.host) {
      const destination = destinations.get(flow.host) || { host: flow.host, company: flow.company, connections: 0, apps: new Set() };
      destination.connections += 1;
      destination.apps.add(appName);
      destinations.set(flow.host, destination);
    }
  });
  activeFlows.forEach((flow) => {
    if (Number.isFinite(flow.traffic?.uploadBytes) && flow.traffic.uploadBytes >= 0) { activeUploadedBytes += flow.traffic.uploadBytes; hasActiveUploadMeasurements = true; }
  });
  return { idleFlows, activeFlows, apps, destinations, uploadedBytes, hasUploadMeasurements, activeUploadedBytes, hasActiveUploadMeasurements, sensitiveSignals: idleFlows.reduce((sum, flow) => sum + (flow.pii?.length || 0), 0) };
}

export function deriveIdentityCorrelations(flows, category = 'all') {
  const groups = new Map();
  flows.forEach((flow) => (flow.pii || []).forEach((signal) => {
    const proof = signal.correlation;
    if (!proof || proof.scheme !== 'hmac-sha256' || proof.pseudonymized !== true || typeof proof.fingerprint !== 'string' || !/^[a-f0-9]{64}$/i.test(proof.fingerprint)) return;
    if (category !== 'all' && signal.type !== category) return;
    const group = groups.get(proof.fingerprint) || { fingerprint: proof.fingerprint, type: signal.type, apps: new Set(), destinations: new Set(), flows: [], first: flow.ts, last: flow.ts, confidence: proof.confidence };
    group.apps.add(flow.app || 'Unknown app');
    if (flow.host) group.destinations.add(flow.host);
    group.flows.push(flow);
    if (new Date(flow.ts) < new Date(group.first)) group.first = flow.ts;
    if (new Date(flow.ts) > new Date(group.last)) group.last = flow.ts;
    if (typeof proof.confidence === 'number' && Number.isFinite(proof.confidence) && proof.confidence >= 0 && proof.confidence <= 1) group.confidence = Math.min(group.confidence ?? 1, proof.confidence);
    groups.set(proof.fingerprint, group);
  }));
  return [...groups.values()].filter((group) => group.apps.size > 1).sort((a,b)=>b.apps.size-a.apps.size || b.flows.length-a.flows.length);
}

export function availableCorrelationCategories(flows) {
  return [...new Set(flows.flatMap((flow) => (flow.pii || []).filter((signal) => {
    const proof = signal.correlation;
    return proof?.scheme === 'hmac-sha256' && proof?.pseudonymized === true && typeof proof.fingerprint === 'string' && /^[a-f0-9]{64}$/i.test(proof.fingerprint);
  }).map((signal) => signal.type)))];
}
