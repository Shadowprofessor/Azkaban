// Checks the TS feature port against fixtures generated from azkaban_agent/tracker_features.py.
import fs from "node:fs";
import ts from "typescript";
const src = fs.readFileSync(new URL("../lib/trackerFeatures.ts", import.meta.url), "utf8");
const js = ts.transpileModule(src, { compilerOptions: { module: ts.ModuleKind.ESNext, target: ts.ScriptTarget.ES2022 } }).outputText;
const mod = await import("data:text/javascript;base64," + Buffer.from(js).toString("base64"));
const fx = JSON.parse(fs.readFileSync(new URL("./feature_fixture.json", import.meta.url)));
let bad = 0, n = 0;
for (const [d, exp] of Object.entries(fx.lexical)) {
  const got = mod.lexical(d);
  for (const [k, v] of Object.entries(exp)) { n++; if (Math.abs(got[k] - v) > 1e-9) { bad++; console.log("MISMATCH", d, k, v, got[k]); } }
}
for (const c of fx.behaviour) {
  const got = mod.behaviourFromPages(c.pages);
  for (const [k, v] of Object.entries(c.features)) {
    n++;
    const ok = v === null ? Number.isNaN(got[k]) || got[k] === undefined : Math.abs(got[k] - v) <= 1e-9;
    if (!ok) { bad++; console.log("MISMATCH beh", k, v, got[k]); }
  }
}
console.log(`feature parity: ${n - bad}/${n} values match`);
process.exit(bad ? 1 : 0);
