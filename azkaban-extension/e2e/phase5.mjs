import { launch, startSite } from "./harness.mjs";
const site = await startSite();
const { ctx, sw } = await launch();
const page = await ctx.newPage();
await page.goto(site.url);
await page.fill("#email", "ginny.weasley@hogwarts.test");
await page.locator("#phone").click(); // blur -> change -> SDK beacons the email (no submit)
await page.waitForTimeout(2500);
const tabId = await sw.evaluate(async () => (await chrome.tabs.query({ url: "http://127.0.0.1/*" }))[0]?.id);
const t = await sw.evaluate(async (id) => (await chrome.storage.session.get(`tab:${id}`))[`tab:${id}`], tabId);
console.log("harvest:", JSON.stringify(t?.harvest?.map(({ ts, ...h }) => h)));
const dump = JSON.stringify(await sw.evaluate(async () => [await chrome.storage.session.get(null), await chrome.storage.local.get(null)]));
console.log("typed value in storage?", dump.includes("ginny.weasley"), "| base64 in storage?", dump.includes(Buffer.from("ginny.weasley@hogwarts.test").toString("base64").slice(0, 20)));
await ctx.close(); site.close();
