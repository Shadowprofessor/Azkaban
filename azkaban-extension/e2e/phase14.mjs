// Phase 14: the extension must never break signing in.
//
// Google refuses to sign you in when page APIs look tampered with. This checks, in real
// Chromium with the built extension:
//  - on accounts.google.com (served locally via Playwright routing, same URL) no content
//    script runs: fetch/XHR/canvas are the browser's own;
//  - on an ordinary site the probe still runs (control, so the check above means something);
//  - with Patronus AND third-party cookie stripping on, Google sign-in requests are allowed
//    while a real tracker is still blocked;
//  - with Patronus off, no blocking rule is left behind.
import { launch, startSite } from "./harness.mjs";

let fail = 0;
const ok = (c, m) => { if (!c) { console.log("FAIL " + m); fail++; } else console.log("ok   " + m); };
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const site = await startSite();
const { ctx, sw, extId } = await launch();
const LOGIN = "<!doctype html><title>Sign in</title><input type=password id=p><script>window.ready=1</script>";
for (const u of ["https://accounts.google.com/**", "https://github.com/login**"]) {
  await ctx.route(u, (r) => r.fulfill({ status: 200, contentType: "text/html", body: LOGIN }));
}

const tampered = (page) => page.evaluate(() => ({
  fetch: !Function.prototype.toString.call(window.fetch).includes("[native code]"),
  xhr: !Function.prototype.toString.call(XMLHttpRequest.prototype.open).includes("[native code]"),
}));

const login = await ctx.newPage();
await login.goto("https://accounts.google.com/v3/signin/identifier?flowName=GlifWebSignIn");
await sleep(500);
let t = await tampered(login);
ok(!t.fetch && !t.xhr, "accounts.google.com: fetch and XHR are untouched (no probe)");
await login.goto("https://github.com/login");
await sleep(300);
t = await tampered(login);
ok(!t.fetch && !t.xhr, "github.com/login: untouched");

const normal = await ctx.newPage();
await normal.goto(site.url);
await sleep(500);
t = await tampered(normal);
ok(t.fetch, "control: an ordinary site still gets the leak probe");

// Worst case: everything on.
const popup = await ctx.newPage();
await popup.goto(`chrome-extension://${extId}/popup.html`);
await popup.evaluate(async () => {
  await chrome.runtime.sendMessage({ type: "patronus", action: "toggle", on: true });
  await chrome.runtime.sendMessage({ type: "patronus", action: "thirdPartyCookies", on: true });
});
await sleep(600);
const outcome = (url, type = "script") => sw.evaluate(async ([url, type]) => {
  const r = await chrome.declarativeNetRequest.testMatchOutcome({ url, type, initiator: "https://news.example", tabId: -1 });
  return r.matchedRules.map((m) => m.ruleId);
}, [url, type]);
for (const [url, type] of [
  ["https://accounts.google.com/v3/signin/identifier", "sub_frame"],
  ["https://www.gstatic.com/_/mss/boq-identity/_/js/k=boq.js", "script"],
  ["https://ssl.gstatic.com/accounts/ui/logo.png", "image"],
  ["https://apis.google.com/js/platform.js", "script"],
]) {
  const ids = await outcome(url, type);
  ok(ids.length === 1 && ids[0] === 1, `allowed with Patronus on: ${new URL(url).hostname} (rules ${JSON.stringify(ids)})`);
}
const ga = await outcome("https://www.google-analytics.com/collect");
ok(ga.length && ga[0] !== 1, `a real tracker is still blocked (rules ${JSON.stringify(ga)})`);

// Patronus off again: nothing that blocks may remain.
await popup.evaluate(async () => {
  await chrome.runtime.sendMessage({ type: "patronus", action: "toggle", on: false });
  await chrome.runtime.sendMessage({ type: "patronus", action: "thirdPartyCookies", on: false });
});
await sleep(600);
const left = await sw.evaluate(async () => (await chrome.declarativeNetRequest.getDynamicRules()).map((r) => r.action.type));
ok(left.every((a) => a === "allow"), `Patronus off leaves no blocking rule (${JSON.stringify(left)})`);

await ctx.close(); site.close();
console.log(fail ? `\n${fail} FAILURES` : "\nphase 14 passes: sign-in pages are never touched or blocked");
process.exit(fail ? 1 : 0);
