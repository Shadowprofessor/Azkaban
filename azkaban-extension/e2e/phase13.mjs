// Phase 13: live sync, browser -> extension -> agent -> website, plus cookie blocking.
//
// 1. Real Chromium with the built extension browses the fixture shop.
// 2. Every request lands in the extension's ring with status/type/timing/cookie facts,
//    including the ones Patronus blocked.
// 3. Those exact records, through lib/bridgeProtocol.ts, go to the REAL agent (Agent class,
//    replay mode so no history file is touched) on a spare port.
// 4. A dashboard-origin consumer receives them as `flow` messages and the website's own
//    adapter (dashboard/src/adapter.js) accepts every one.
// 5. Cookie blocking: DNR strip rules exist, the jar is purged, and a cookie written after
//    the block is removed again.
import { spawn } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { launch, startSite } from "./harness.mjs";
import { flowsMsg, helloMsg, toWireFlow } from "../lib/bridgeProtocol.ts";
import { normalise } from "../../dashboard/src/adapter.js";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..", "..");
const PORT = 8794;
const EXT_ORIGIN = "chrome-extension://" + "b".repeat(32);
let fail = 0;
const ok = (c, m) => { if (!c) { console.log("FAIL " + m); fail++; } else console.log("ok   " + m); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

// ------------------------------------------------------------------ 1-2. capture in Chromium
const site = await startSite();
const { ctx, sw, extId } = await launch();
const page = await ctx.newPage();
await page.goto(site.url);
await sleep(300);
await page.reload(); // a real navigation in an existing tab (the first goto opens the tab)
await page.evaluate(() => window.fireTrackers());
await sleep(2500);
let flows = await sw.evaluate(async () => (await chrome.storage.session.get("flows")).flows ?? []);
const doc = flows.find((f) => f.rtype === "main_frame");
ok(flows.length >= 3, `extension recorded every request (${flows.length})`);
ok(!!doc && doc.status === 200 && doc.method === "GET", "page load has method + HTTP status");
ok(flows.every((f) => typeof f.ms === "number" && f.scheme && Array.isArray(f.queryKeys)), "every request has timing, scheme, parameter names");
ok(!flows.some((f) => f.id.startsWith("ext-body-")), "no duplicate half-rows: body findings merged into their request");
ok(flows.some((f) => f.pii?.length), "body findings (PII) survive the merge");
const ga = flows.find((f) => f.host.includes("google-analytics"));
ok(!!ga && ga.queryKeys.includes("cid") && !JSON.stringify(ga).includes("987654321"), "query NAMES kept, query VALUES never stored");

// Patronus on: the blocked requests must still appear in the list, marked blocked.
const popup = await ctx.newPage();
await popup.goto(`chrome-extension://${extId}/popup.html`);
await popup.evaluate(() => chrome.runtime.sendMessage({ type: "patronus", action: "toggle", on: true }));
await page.bringToFront();
await page.evaluate(() => window.fireTrackers());
await sleep(2500);
flows = await sw.evaluate(async () => (await chrome.storage.session.get("flows")).flows ?? []);
ok(flows.some((f) => f.blocked === "request"), "requests Patronus blocked are listed as blocked");

// ------------------------------------------------------------------ 5. cookie blocking
await sw.evaluate(() => chrome.cookies.set({ url: "https://tracker-test.example/", name: "uid", value: "abc123", expirationDate: Date.now() / 1000 + 3600 }));
let before = await sw.evaluate(() => chrome.cookies.getAll({ domain: "tracker-test.example" }));
ok(before.length === 1, "fixture cookie planted");
await popup.evaluate(() => chrome.runtime.sendMessage({ type: "patronus", action: "cookieBlock", domains: ["tracker-test.example"] }));
await sleep(500);
let after = await sw.evaluate(() => chrome.cookies.getAll({ domain: "tracker-test.example" }));
ok(after.length === 0, "blocking a domain purges the cookies it already had");
await sw.evaluate(() => chrome.cookies.set({ url: "https://tracker-test.example/", name: "uid2", value: "x", expirationDate: Date.now() / 1000 + 3600 }));
await sleep(700);
after = await sw.evaluate(() => chrome.cookies.getAll({ domain: "tracker-test.example" }));
ok(after.length === 0, "a cookie written after the block is removed again");
await popup.evaluate(() => chrome.runtime.sendMessage({ type: "patronus", action: "thirdPartyCookies", on: true }));
await sleep(500);
const rules = await sw.evaluate(async () => (await chrome.declarativeNetRequest.getDynamicRules()).filter((r) => r.action.type === "modifyHeaders"));
ok(rules.some((r) => r.condition.requestDomains?.includes("tracker-test.example")), "DNR strips Cookie/Set-Cookie for the blocked domain");
ok(rules.some((r) => r.condition.domainType === "thirdParty"), "DNR strips cookies on every third-party request when asked");
ok(rules.every((r) => r.action.requestHeaders?.[0]?.header === "cookie" && r.action.responseHeaders?.[0]?.header === "set-cookie"), "rules remove both directions");
await ctx.close(); site.close();

// ------------------------------------------------------------------ 3-4. agent and website
const PY = `
import asyncio, sys
sys.path.insert(0, ${JSON.stringify(path.join(root, "azkaban-agent"))})
from azkaban_agent.agent import Agent
from azkaban_agent.config import Config
from azkaban_agent.wsserver import start_ws
async def main():
    a = Agent(Config(), mode="replay")
    print("HISTORY " + str(a.history.enabled), flush=True)
    srv = await start_ws(a.hub, ${PORT})
    print("READY", flush=True)
    await asyncio.sleep(20)
    srv.close()
asyncio.run(main())
`;
const agent = spawn(process.platform === "win32" ? "python" : "python3", ["-c", PY], { cwd: root, stdio: ["ignore", "pipe", "pipe"] });
const lines = [];
agent.stdout.on("data", (b) => String(b).split("\n").filter(Boolean).forEach((l) => lines.push(l.trim())));
agent.stderr.on("data", () => {});
for (let i = 0; i < 300 && !lines.includes("READY"); i++) await sleep(100);
ok(lines.includes("READY"), "real agent started");
ok(lines.includes("HISTORY False"), "a non-live agent does not write the history file");

const dash = new WebSocket(`ws://127.0.0.1:${PORT}/ws`, { headers: { Origin: "http://127.0.0.1:5173" } });
const got = [];
dash.addEventListener("message", (e) => got.push(JSON.parse(e.data)));
await new Promise((res, rej) => { dash.addEventListener("open", res); dash.addEventListener("error", rej); });
const ext = new WebSocket(`ws://127.0.0.1:${PORT}/ws/extension`, { headers: { Origin: EXT_ORIGIN } });
await new Promise((res, rej) => { ext.addEventListener("open", res); ext.addEventListener("error", rej); });
ext.send(JSON.stringify(helloMsg("0.1.0")));
ext.send(JSON.stringify(flowsMsg(flows.map(toWireFlow))));
await sleep(2500);
const live = got.filter((m) => m.type === "flow" && m.flow?.source === "extension");
ok(live.length === flows.length, `website received every browser request live (${live.length}/${flows.length})`);
const accepted = live.map((m) => normalise(m)).filter((m) => m?.type === "flow");
ok(accepted.length === live.length, "the website's adapter accepts all of them");
const gaFlow = accepted.find((m) => m.data.host.includes("google-analytics"));
ok(!!gaFlow && gaFlow.data.tracker && gaFlow.data.company, "agent enriched browser requests with tracker + company");
ok(accepted.some((m) => m.data.blocked === "request"), "blocked state reaches the website");
ok(accepted.some((m) => m.data.traffic?.status === 200), "HTTP status reaches the website");
dash.close(); ext.close(); agent.kill();

console.log(fail ? `\n${fail} FAILURES` : "\nphase 13 passes: browser requests stream live to the website; cookie blocking works");
process.exit(fail ? 1 : 0);
