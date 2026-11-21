import { launch, startSite } from "./harness.mjs";
const site = await startSite();
const { ctx, sw } = await launch();
// The user's own email, stored only as hashes (what the options page will do).
await sw.evaluate(async () => {
  const h = async (a, s) => [...new Uint8Array(await crypto.subtle.digest(a, new TextEncoder().encode(s)))].map((b) => b.toString(16).padStart(2, "0")).join("");
  const em = "harry.potter@hogwarts.test";
  await chrome.storage.local.set({ settings: { knownHashes: [await h("SHA-256", em), await h("SHA-1", em)] } });
});
const page = await ctx.newPage();
const errors = []; page.on("pageerror", (e) => errors.push(String(e)));
await page.goto(site.url);
await page.evaluate(() => window.fireTrackers());
await page.waitForTimeout(3000);
const flows = await sw.evaluate(async () => (await chrome.storage.session.get("flows")).flows ?? []);
for (const f of flows.filter((f) => f.pii.length)) console.log(" ", f.host, JSON.stringify(f.pii.map((p) => [p.type, p.redacted])), f.findings?.map((x) => x.detail).join(";") ?? "");
const dump = JSON.stringify(await sw.evaluate(async () => [await chrome.storage.session.get(null), await chrome.storage.local.get(null)]));
for (const raw of ["harry.potter@hogwarts.test", "6f1c2a9e-4b7d-4e21-9c3a-5d8e7f0a1b2c", "12.971599", "9876500042"]) console.log("raw in storage?", raw, dump.includes(raw));
console.log("page errors:", errors.length);
await ctx.close(); site.close();
