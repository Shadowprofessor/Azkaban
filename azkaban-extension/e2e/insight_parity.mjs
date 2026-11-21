// Step 6 consistency check: the extension must produce the byte-identical unknown_tracker insight
// the agent produced for the same page observations.  Usage: node e2e/insight_parity.mjs expected.json
import fs from "node:fs";
import { launch } from "./harness.mjs";
const exp = JSON.parse(fs.readFileSync(process.argv[2], "utf8"));
const { ctx, extId } = await launch();
const page = await ctx.newPage();
await page.goto(`chrome-extension://${extId}/popup.html`);
const got = await page.evaluate(({ domain, pages }) => chrome.runtime.sendMessage({ type: "clf_selftest", domain, pages }), exp);
const a = JSON.stringify(exp.insight), b = JSON.stringify(got);
console.log("agent    :", a);
console.log("extension:", b);
console.log(a === b ? "BYTE-IDENTICAL" : "DRIFT");
await ctx.close();
process.exit(a === b ? 0 : 1);
