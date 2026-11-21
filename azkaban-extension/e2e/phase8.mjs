// Phase 8 acceptance: real-world-ish shapes must land on the documented grades.
import { computeSiteScore, breakdownLine, CAP } from "../lib/scoring.ts";
const cases = [
  ["privacy-respecting site", { trackers: 0, unknownTrackers: 0, thirdParties: 1, cookies: 2 }, "A"],
  ["google.com-ish",          { trackers: 3, unknownTrackers: 0, thirdParties: 8, cookies: 12 }, "B"],
  ["news site, 15 trackers",  { trackers: 15, unknownTrackers: 2, thirdParties: 22, cookies: 30, fingerprinting: true }, "F"],
  // 6 known trackers already max the tracker cap (6 x 5 = 30), so the agreed curve is
  // steep here: a page needs few trackers to stay above D, which is the intent.
  ["moderate news site",      { trackers: 6, unknownTrackers: 1, thirdParties: 14, cookies: 18 }, "D"],
  ["light news site",         { trackers: 2, unknownTrackers: 0, thirdParties: 9, cookies: 14 }, "B"],
  ["heavy, no fingerprinting",{ trackers: 10, unknownTrackers: 1, thirdParties: 18, cookies: 25 }, "D"],
  ["empty page",              {}, "A"],
];
let fail = 0;
for (const [name, input, want] of cases) {
  const r = computeSiteScore(input);
  const ok = r.grade === want;
  if (!ok) fail++;
  console.log(`${ok ? "ok  " : "FAIL"} ${name.padEnd(26)} score=${String(r.score).padStart(3)} grade=${r.grade} (want ${want})`);
  console.log(`     ${breakdownLine(r.breakdown)}`);
}
// invariants
const worst = computeSiteScore({ trackers: 999, unknownTrackers: 999, thirdParties: 999, cookies: 999, fingerprinting: true });
console.log(`\ncaps sum to ${Object.values(CAP).reduce((a, b) => a + b, 0)}; worst case score=${worst.score} grade=${worst.grade}`);
if (worst.score !== 0 || worst.grade !== "F") { console.log("FAIL worst case"); fail++; }
// garbage in
const junk = computeSiteScore({ trackers: NaN, cookies: -5, thirdParties: undefined });
if (junk.score !== 100) { console.log("FAIL junk input -> " + junk.score); fail++; } else console.log("ok   junk input ignored");
// allowances
if (computeSiteScore({ thirdParties: 5 }).score !== 100) { console.log("FAIL third-party allowance"); fail++; } else console.log("ok   5 third parties are free");
if (computeSiteScore({ cookies: 10 }).score !== 100) { console.log("FAIL cookie allowance"); fail++; } else console.log("ok   10 cookies are free");
console.log(fail ? `\n${fail} FAILURES` : "\nall scoring checks pass");
if (fail) process.exit(1);

// ---------------------------------------------------------------- live popup
// Needs a Playwright Chromium. Skipped (not failed) where one is unavailable, so this
// file is still useful in a sandbox without browser downloads.
let launch, startSite;
try {
  ({ launch, startSite } = await import("./harness.mjs"));
  await (await import("@playwright/test")).chromium.executablePath();
} catch {
  console.log("\nskip: no Playwright Chromium available; pure-logic checks above still ran");
  process.exit(0);
}
let site, ctx;
try {
  site = await startSite(4788);
  ({ ctx } = await launch());
} catch (e) {
  console.log(`\nskip: could not launch Chromium (${e.message.split("\n")[0]})`);
  process.exit(0);
}
const { extId, sw } = await (async () => {
  let [s] = ctx.serviceWorkers();
  if (!s) s = await ctx.waitForEvent("serviceworker");
  return { sw: s, extId: new URL(s.url()).host };
})();
const page = await ctx.newPage();
await page.goto(site.url);
await page.evaluate(() => window.fireTrackers?.());
await page.waitForTimeout(2000);
const tabId = await sw.evaluate(async () => (await chrome.tabs.query({ url: "http://127.0.0.1/*" }))[0]?.id);
const popup = await ctx.newPage();
await popup.goto(`chrome-extension://${extId}/popup.html?tab=${tabId}`);
await popup.waitForSelector("[data-testid=grade]");
const grade = (await popup.textContent("[data-testid=grade]")).trim();
const value = (await popup.textContent("[data-testid=score-value]")).trim();
const line = (await popup.textContent("[data-testid=breakdown]")).trim();
console.log(`\nlive popup -> grade=${grade} score=${value} breakdown="${line}"`);
const stored = await sw.evaluate(async (id) => (await chrome.storage.session.get(`tab:${id}`))[`tab:${id}`], tabId);
console.log(`stored on tab -> score=${stored?.score} grade=${stored?.grade}`);
let bad = 0;
if (!"ABCDF".includes(grade)) { console.log("FAIL grade is not a letter"); bad++; }
if (stored?.grade !== grade) { console.log("FAIL popup grade disagrees with the stored grade"); bad++; }
await popup.screenshot({ path: "e2e/popup8.png" });
await ctx.close(); site.close();
console.log(bad ? `${bad} LIVE FAILURES` : "live popup checks pass");
process.exit(bad ? 1 : 0);
