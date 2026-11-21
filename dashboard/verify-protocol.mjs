// Replays REAL agent output through the dashboard's adapter + validator and reports
// what the UI would end up holding. No hand-written fixtures: every line below came off
// the agent's own WebSocket.
import fs from 'node:fs';
import { normalise } from './src/adapter.js';
import { validateInbound } from './src/schema.js';

// Capture a session's messages with:
//   python azkaban-agent/scripts/ws_probe.py 30 > /tmp/probe.jsonl
// then:  npm run verify:protocol -- /tmp/probe.jsonl
const path = process.argv[2] || '/tmp/probe.jsonl';
if (!fs.existsSync(path)) {
  console.log(`no capture at ${path}\n` +
    'record one while the agent is running:\n' +
    '  python azkaban-agent/scripts/ws_probe.py 30 > /tmp/probe.jsonl');
  process.exit(0);
}
const lines = fs.readFileSync(path, 'utf8').split('\n');
const seen = {}, kept = {}, dropped = {};
const state = { flows: [], verdicts: {}, score: null, insights: [], evidence: null, agent: null, errors: [] };

for (const line of lines) {
  const i = line.indexOf('{');
  if (i < 0) continue;
  let raw;
  try { raw = JSON.parse(line.slice(i)); } catch { continue; }
  seen[raw.type] = (seen[raw.type] ?? 0) + 1;
  const msg = normalise(raw, () => 'hosts');
  if (!msg || !validateInbound(msg)) { dropped[raw.type] = (dropped[raw.type] ?? 0) + 1; continue; }
  kept[raw.type] = (kept[raw.type] ?? 0) + 1;
  const d = msg.data;
  if (msg.type === 'flow') state.flows.push(d);
  if (msg.type === 'verdict') state.verdicts[d.flowId] = d;
  if (msg.type === 'score') state.score = d;
  if (msg.type === 'insight') state.insights = [d, ...state.insights.filter((x) => x.key !== d.key)];
  if (msg.type === 'evidence') state.evidence = d;
  if (msg.type === 'status') state.agent = d;
  if (msg.type === 'error') state.errors.push(d);
}

console.log('agent sent   :', JSON.stringify(seen));
console.log('UI accepted  :', JSON.stringify(kept));
console.log('UI dropped   :', JSON.stringify(dropped));
console.log();
console.log(`flows in store     : ${state.flows.length}`);
console.log(`insights in store  : ${state.insights.length}`);
console.log(`with remediation   : ${state.insights.filter((i) => i.remediation).length}`);
console.log(`exposure score     : ${state.score ? Math.round(state.score.total) + '/1000' : 'none'}`);
console.log(`score categories   : ${state.score ? state.score.categories.map((c) => c.name + '=' + c.value).join(', ') : '-'}`);
console.log(`agent status       : mode=${state.agent?.mode} capturing=${state.agent?.capturing} v${state.agent?.agentVersion}`);
console.log(`engines            : ${JSON.stringify(state.agent?.engines)}`);

// What the Leak Radar table actually renders for one row.
const withPii = state.flows.find((f) => f.pii.length);
if (withPii) {
  console.log();
  console.log('sample radar row:');
  console.log(`  ts       ${withPii.ts}`);
  console.log(`  app      ${withPii.app} -> ${withPii.host} (${withPii.company || 'unattributed'})`);
  console.log(`  country  ${withPii.country}   severity ${withPii.severity}   bytes ${withPii.bytes}`);
  console.log(`  pii      ${withPii.pii.map((p) => p.type + ':' + p.redacted).join(', ')}`);
  console.log(`  tcf      ${withPii.tcf ? withPii.tcf.vendors + ' vendors / ' + withPii.tcf.purposes.length + ' purposes' : 'none'}`);
}
const fix = state.insights.find((i) => i.remediation);
if (fix) {
  console.log();
  console.log('sample finding on the Insights page:');
  console.log(`  ${fix.level.toUpperCase()}  ${fix.title}`);
  console.log(`  fix [${fix.remediation.source}] ${fix.remediation.title}`);
  fix.remediation.steps.forEach((s, n) => console.log(`    ${n + 1}. ${s.slice(0, 92)}`));
}
// Fail loudly if anything the agent sent would vanish.
const lost = Object.keys(dropped).filter((k) => k !== undefined);
if (lost.length) { console.log('\nFAIL: UI would silently drop ' + JSON.stringify(dropped)); process.exit(1); }
console.log('\nevery message the agent sent is accepted by the dashboard');
