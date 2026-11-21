// Does the extension talk to anything but loopback?
//
// The naive grep for "fetch|http" drowns in false positives: httpOnly, an `https: boolean`
// feature field, browser.runtime.getURL for the bundled model. A check nobody can read is
// a check nobody runs, so this looks for actual network calls and resolves their target.
//
//   node scripts/check-extension-egress.mjs
import fs from "node:fs";
import path from "node:path";

const ROOT = "azkaban-extension";
const DIRS = ["lib", "entrypoints"];
const LOOPBACK = /^(wss?|https?):\/\/(127\.0\.0\.1|localhost|\[::1\])(:\d+)?(\/|$)/i;

// Calls that reach the network. getURL/runtime URLs are extension-local, not network.
const CALLS = [
  { re: /\bfetch\s*\(\s*([^)]*)/g, what: "fetch" },
  { re: /new\s+WebSocket\s*\(\s*([^)]*)/g, what: "WebSocket" },
  // Only construction counts. probe.content.ts patches XMLHttpRequest.prototype to
  // OBSERVE the page's own requests, which is the opposite of making one.
  { re: /new\s+XMLHttpRequest\s*\(/g, what: "new XMLHttpRequest" },
  { re: /\bnavigator\.sendBeacon\s*\(/g, what: "sendBeacon" },
  { re: /new\s+EventSource\s*\(\s*([^)]*)/g, what: "EventSource" },
  { re: /\bimportScripts\s*\(/g, what: "importScripts" },
];

function walk(dir) {
  const out = [];
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isDirectory()) out.push(...walk(p));
    else if (/\.ts$/.test(e.name) && !/\.d\.ts$/.test(e.name)) out.push(p);
  }
  return out;
}

const findings = [];
let checked = 0;
for (const dir of DIRS) {
  const full = path.join(ROOT, dir);
  if (!fs.existsSync(full)) continue;
  for (const file of walk(full)) {
    checked++;
    const src = fs.readFileSync(file, "utf8");
    const lines = src.split("\n");
    for (const { re, what } of CALLS) {
      re.lastIndex = 0;
      let m;
      while ((m = re.exec(src))) {
        const line = src.slice(0, m.index).split("\n").length;
        const arg = (m[1] ?? "").trim();
        // Extension-local resources are not network egress.
        if (/runtime\.getURL|import\.meta\.url/.test(arg)) continue;
        // A literal URL: must be loopback.
        const lit = arg.match(/^["'`]([^"'`]+)["'`]/);
        if (lit && LOOPBACK.test(lit[1])) continue;
        // A constant: resolve it in-file and check its value.
        const ident = arg.match(/^([A-Z_][A-Z0-9_]*)\b/);
        if (ident) {
          const decl = src.match(new RegExp(`${ident[1]}\\s*=\\s*["'\`]([^"'\`]+)["'\`]`));
          if (decl && LOOPBACK.test(decl[1])) continue;
        }
        findings.push({ file, line, what, arg: arg.split("\n")[0].slice(0, 70), src: lines[line - 1]?.trim().slice(0, 90) });
      }
    }
  }
}

console.log(`checked ${checked} TypeScript files under ${DIRS.map((d) => ROOT + "/" + d).join(", ")}`);
if (!findings.length) {
  console.log("egress check OK: every network call targets loopback or a bundled resource");
  process.exit(0);
}
console.log(`\negress check FAILED: ${findings.length} call(s) not provably loopback\n`);
for (const f of findings) console.log(`  ${f.file}:${f.line}  ${f.what}(${f.arg})\n    ${f.src}`);
process.exit(1);
