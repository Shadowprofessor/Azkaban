// Offline queue: findings recorded while the agent is down must arrive once it returns.
// Runs the REAL Python agent, and the real wire format from lib/bridgeProtocol.ts.
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { detectionMsg, helloMsg } from "../lib/bridgeProtocol.ts";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const PORT = 8797;
const EXT = "chrome-extension://" + "a".repeat(32);
let fail = 0;
const ok = (c, m) => { if (!c) { console.log("FAIL " + m); fail++; } else console.log("ok   " + m); };

// --- a storage.local stand-in, so the queue logic is exercised exactly as shipped
const local = new Map();
const queue = {
  async read() { const q = local.get("bridgeQueue"); return Array.isArray(q) ? q : []; },
  async write(items) { local.set("bridgeQueue", items.slice(-500)); },
};

const PY = `
import asyncio, json, sys
sys.path.insert(0, ${JSON.stringify(path.join(root, "azkaban-agent"))})
from azkaban_agent.extbridge import ExtensionBridge
from azkaban_agent.wsserver import Hub, start_ws
def status(): return {"type":"status","version":"0.1.0","mode":"live","engines":{"rag":True}}
async def main():
    async def on_det(d): print("GOT " + d["domain"], flush=True)
    async def on_score(s): pass
    hub = Hub(status, None, extension=ExtensionBridge(status, on_det, on_score))
    srv = await start_ws(hub, ${PORT})
    print("READY", flush=True)
    await asyncio.sleep(25)
    srv.close()
asyncio.run(main())
`;

// ---------------------------------------------------------------- agent is DOWN
const made = ["ads-one.example", "ads-two.example", "ads-three.example"];
for (const domain of made) {
  const q = await queue.read();
  q.push(detectionMsg({ kind: "unknown_tracker", host: domain, domain, site: "news.example", confidence: 0.9 }));
  await queue.write(q);
}
ok((await queue.read()).length === 3, "3 findings queued while the agent was down");

// ---------------------------------------------------------------- agent comes back
const agent = spawn("python3", ["-c", PY], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
const lines = [];
agent.stdout.on("data", (b) => String(b).split("\n").filter(Boolean).forEach((l) => lines.push(l)));
const waitFor = async (pred, ms = 12000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { const h = lines.find(pred); if (h) return h; await new Promise((r) => setTimeout(r, 100)); }
  return null;
};
if (!(await waitFor((l) => l.startsWith("READY")))) { console.log("FAIL agent did not start"); agent.kill(); process.exit(1); }

const ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws/extension`, { headers: { Origin: EXT } });
await new Promise((res, rej) => { ws.addEventListener("open", res); ws.addEventListener("error", rej); });
const acked = new Promise((res) => ws.addEventListener("message", (e) => { if (JSON.parse(e.data).type === "producer_ack") res(); }));
ws.send(JSON.stringify(helloMsg("0.1.0")));
await acked;
ok(true, "reconnected and handshook");

// drain, exactly as agentBridge.drain does
let q = await queue.read();
let sent = 0;
while (q.length) { ws.send(JSON.stringify(q[0])); q = q.slice(1); sent++; await queue.write(q); }
ok(sent === 3, "queue drained on reconnect");
ok((await queue.read()).length === 0, "queue emptied after draining");

for (const domain of made) ok(!!(await waitFor((l) => l === "GOT " + domain, 6000)), `agent received ${domain}`);

ws.close(); agent.kill();
console.log(fail ? `\n${fail} FAILURES` : "\nnothing was lost while the agent was down");
process.exit(fail ? 1 : 0);
