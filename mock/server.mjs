import { WebSocketServer } from 'ws';
import { randomUUID } from 'node:crypto';

const PORT = Number(process.env.GHOSTPRINT_MOCK_PORT || 8787);
const wss = new WebSocketServer({ host: '127.0.0.1', port: PORT });
const apps = ['Chrome', 'Slack', 'Spotify', 'WhatsApp', 'Instagram'];
const hosts = [
  ['graph.facebook.com', 'Meta', 'US', 'Meta Pixel', 'analytics'],
  ['app-measurement.com', 'Google', 'US', 'Firebase Analytics', 'analytics'],
  ['api.segment.io', 'Twilio', 'US', 'Segment', 'analytics'],
  ['sdk.appsflyer.com', 'AppsFlyer', 'IL', 'AppsFlyer', 'attribution'],
  ['api.spotify.com', 'Spotify', 'SE', 'Spotify API', 'service'],
  ['events.reddit.com', 'Reddit', 'US', 'Reddit Pixel', 'advertising'],
];
const piiTypes = ['adid', 'gps', 'email', 'phone', 'contact', 'clipboard'];
const pick = (items) => items[Math.floor(Math.random() * items.length)];
const redacted = { adid: 'a1b2••••••••••••9c', gps: '28.61••, 77.20••', email: 'n••••t@example.com', phone: '+91 ••••• ••482', contact: '[1 contact redacted]', clipboard: '[clipboard value redacted]' };
let sequence = 0;
let blockedHosts = new Set();

function send(ws, type, data) {
  if (ws.readyState === ws.OPEN) ws.send(JSON.stringify({ type, data }));
}

function makeFlow() {
  const [host, company, country, trackerName, category] = pick(hosts);
  const isBlocked = blockedHosts.has(host);
  const hasPii = !isBlocked && Math.random() > 0.45;
  const type = pick(piiTypes);
  const severity = hasPii ? Math.round(52 + Math.random() * 46) : Math.round(Math.random() * 38);
  return {
    id: `mock-${++sequence}`,
    ts: new Date().toISOString(),
    app: pick(apps),
    host,
    method: Math.random() > 0.4 ? 'POST' : 'GET',
    path: ['/v1/collect', '/events/batch', '/g/collect', '/track'][Math.floor(Math.random() * 4)],
    ip: '104.18.2.1',
    country,
    company,
    tracker: { name: trackerName, category },
    decrypted: Math.random() > 0.22,
    pii: hasPii ? [{ type, redacted: redacted[type], confidence: Number((0.84 + Math.random() * 0.15).toFixed(2)) }] : [],
    severity,
    tcf: Math.random() > 0.72 ? { vendors: 89, purposes: ['Analytics', 'Personalized advertising'] } : null,
    bytes: Math.round(300 + Math.random() * 4200),
  };
}

function score() {
  return { total: Math.round(360 + Math.random() * 420), categories: [
    { name: 'Trackers', value: Math.round(35 + Math.random() * 55) },
    { name: 'PII leaked', value: Math.round(25 + Math.random() * 65) },
    { name: 'Cross-border', value: Math.round(18 + Math.random() * 58) },
    { name: 'Consent', value: Math.round(12 + Math.random() * 51) },
  ] };
}

function verdict(flow) {
  return {
    flowId: flow.id,
    status: 'questionable',
    reasoning: `Synthetic demo finding: ${flow.pii.length ? `${flow.pii.map((hit) => hit.type.toUpperCase()).join(', ')} signal${flow.pii.length > 1 ? 's were' : ' was'} reported in traffic to ${flow.company || flow.host}.` : 'No personal-data signal was reported in this flow.'} This technical observation alone does not establish a legal violation or compliance. Purpose, notice, consent, responsible entity, jurisdiction, and applicable commencement dates require independent review.`,
    citations: [{ source: 'Digital Personal Data Protection Act, 2023', section: 'Potentially relevant provisions · check phased commencement', url: 'https://www.indiacode.nic.in/bitstream/123456789/22037/1/a2023-22.pdf', sourceType: 'legislation', verifiedAt: '2026-11-22' }],
  };
}

wss.on('connection', (ws) => {
  let capturing = false;
  let timer;
  let count = 0;
  send(ws, 'status', { capturing, device: 'laptop', flows: 0, agentVersion: 'mock-0.1' });
  const emitFlow = () => {
    if (!capturing) return;
    const flow = makeFlow();
    send(ws, 'flow', flow);
    count += 1;
    if (flow.pii.length && Math.random() > 0.2) send(ws, 'verdict', verdict(flow));
    if (count % 5 === 0) send(ws, 'score', score());
  };
  const start = (device = 'laptop') => {
    if (timer) clearInterval(timer);
    capturing = true;
    send(ws, 'status', { capturing, device, flows: count, agentVersion: 'mock-0.1' });
    timer = setInterval(emitFlow, 250);
  };
  const stop = () => {
    capturing = false;
    clearInterval(timer);
    send(ws, 'status', { capturing, device: 'laptop', flows: count, agentVersion: 'mock-0.1' });
  };
  ws.on('message', (raw) => {
    let message;
    try { message = JSON.parse(raw.toString()); } catch { return; }
    if (message.type === 'start') start(message.device);
    if (message.type === 'stop') stop();
    if (message.type === 'analyze') {
      const flow = { ...makeFlow(), id: message.flowId };
      send(ws, 'verdict', verdict(flow));
    }
    if (message.type === 'blocklist') {
      blockedHosts = new Set(hosts.map(([host]) => host));
      const format = message.format || 'hosts';
      const content = format === 'hosts'
        ? [...blockedHosts].map((host) => `0.0.0.0 ${host}`).join('\n')
        : [...blockedHosts].join('\n');
      send(ws, 'blocklist', { format, content });
    }
    if (message.type === 'export_evidence') {
      send(ws, 'evidence', { path: 'ghostprint-evidence-pack.json', sha256: randomUUID().replaceAll('-', '') });
    }
  });
  ws.on('close', () => clearInterval(timer));
});

console.log(`GhostPrint mock agent listening at ws://127.0.0.1:${PORT}`);
