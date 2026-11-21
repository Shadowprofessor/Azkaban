// Phase 10 interop: the exact payloads the extension sends, against the real Python agent.
//
// The two halves of the bridge are written in different languages, so the seam is the
// thing worth testing. This starts the agent's WebSocket server, connects as a producer
// with a chrome-extension origin, and asserts the agent accepts what lib/bridgeProtocol.ts
// produces -- and that the producer path refuses to hand back the flow feed.
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { detectionMsg, helloMsg, pingMsg, siteScoreMsg } from "../lib/bridgeProtocol.ts";
import { computeSiteScore } from "../lib/scoring.ts";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const PORT = 8793;
const EXT_ORIGIN = "chrome-extension://" + "a".repeat(32);
let fail = 0;
const ok = (c, m) => { if (!c) { console.log("FAIL " + m); fail++; } else console.log("ok   " + m); };

// A minimal agent: the real Hub + ExtensionBridge, no proxy or capture.
const PY = `
import asyncio, json, sys
sys.path.insert(0, ${JSON.stringify(path.join(root, "azkaban-agent"))})
from azkaban_agent.extbridge import ExtensionBridge
from azkaban_agent.wsserver import Hub, start_ws

def status():
    return {"type": "status", "version": "0.1.0", "mode": "live",
            "engines": {"llm": True, "rag": True, "model": True, "geo": True}}

async def main():
    seen = []
    async def on_det(d):
        seen.append(d); print("DETECTION " + json.dumps(d), flush=True)
    async def on_score(s):
        seen.append(s); print("SITESCORE " + json.dumps(s), flush=True)
    bridge = ExtensionBridge(status, on_det, on_score)
    hub = Hub(status, None, extension=bridge)
    srv = await start_ws(hub, ${PORT})
    print("READY", flush=True)
    # Publish a flow a producer must never be given.
    await asyncio.sleep(0.6)
    hub.publish({"type": "flow", "flow": {"id": "f1", "host": "secret.example",
                                          "pii": [{"type": "email", "redacted": "a**"}]}})
    await asyncio.sleep(6)
    print("CLIENTS " + str(len(hub.clients)), flush=True)
    srv.close()
asyncio.run(main())
`;

const agent = spawn("python3", ["-c", PY], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
const lines = [];
agent.stdout.on("data", (b) => String(b).split("\n").filter(Boolean).forEach((l) => lines.push(l)));
agent.stderr.on("data", (b) => { const t = String(b).trim(); if (t && !t.includes("Warning")) lines.push("ERR " + t); });
const waitFor = async (pred, ms = 12000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) {
    const hit = lines.find(pred);
    if (hit) return hit;
    await new Promise((r) => setTimeout(r, 100));
  }
  return null;
};

if (!(await waitFor((l) => l.startsWith("READY")))) {
  console.log("FAIL agent did not start:\n  " + lines.join("\n  "));
  agent.kill(); process.exit(1);
}
ok(true, "agent websocket server started");

// ---- producer connection with an extension origin
const ws = new WebSocket(`ws://127.0.0.1:${PORT}/ws/extension`, { headers: { Origin: EXT_ORIGIN } });
const inbox = [];
ws.addEventListener("message", (e) => inbox.push(JSON.parse(e.data)));
await new Promise((res, rej) => { ws.addEventListener("open", res); ws.addEventListener("error", rej); });
ok(true, "producer connected with a chrome-extension origin");

const next = async (ms = 5000) => {
  const end = Date.now() + ms;
  while (Date.now() < end) { if (inbox.length) return inbox.shift(); await new Promise((r) => setTimeout(r, 50)); }
  return null;
};

// ---- handshake
ws.send(JSON.stringify(helloMsg("0.1.0")));
const ack = await next();
ok(ack?.type === "producer_ack", "handshake returns producer_ack");
ok(ack?.agent_version === "0.1.0", "ack carries the agent version");
ok(ack?.engines?.rag === true, "ack carries engine state");

// ---- a detection, exactly as the extension builds it
ws.send(JSON.stringify(detectionMsg({
  kind: "unknown_tracker", host: "quietpixel.io", domain: "quietpixel.io",
  site: "news.example", category: "advertising", confidence: 0.92,
})));
const det = await waitFor((l) => l.startsWith("DETECTION"));
ok(!!det, "agent accepted a browser_detection");
if (det) {
  const d = JSON.parse(det.slice(10));
  ok(d.domain === "quietpixel.io" && d.source === "extension", "detection normalised with source=extension");
  ok(d.category === "advertising" && Math.abs(d.confidence - 0.92) < 1e-6, "category and confidence preserved");
}

// ---- a site score built by the real scoring module
const score = computeSiteScore({ trackers: 3, unknownTrackers: 1, thirdParties: 12, cookies: 14 });
ws.send(JSON.stringify(siteScoreMsg(score, "news.example")));
const sc = await waitFor((l) => l.startsWith("SITESCORE"));
ok(!!sc, "agent accepted a site_score");
if (sc) {
  const s = JSON.parse(sc.slice(10));
  ok(s.site === "news.example" && s.grade === score.grade, `grade round-tripped (${score.grade})`);
  ok(s.breakdown.thirdPartyCount === 12, "breakdown round-tripped");
}

// ---- the boundary: a producer must not receive flows
ws.send(JSON.stringify(pingMsg()));
const pong = await next();
ok(pong?.type === "pong", "producer stays usable");
ok(!inbox.some((m) => m.type === "flow" || m.type === "score"), "producer received no flow and no score");

const clients = await waitFor((l) => l.startsWith("CLIENTS"), 9000);
ok(clients === "CLIENTS 0", "producer was never registered as a feed client");

ws.close(); agent.kill();
console.log(fail ? `\n${fail} FAILURES` : "\nphase 10 interop passes: extension payloads accepted, feed withheld");
process.exit(fail ? 1 : 0);
