import { launch, startSite } from "./harness.mjs";
const site = await startSite();
const { ctx, sw, extId } = await launch();
const errs = [];
sw.on("console", (m) => m.type() !== "log" && errs.push(m.text()));
const page = await ctx.newPage();
for (let i = 0; i < 4; i++) {
  await page.goto(site.url + "article.html?n=" + i);
  await page.waitForTimeout(1200);
}
await page.waitForTimeout(3000);
const st = await sw.evaluate(async () => chrome.storage.session.get(null));
console.log("clf pages:", Object.keys(st["clf:quietpixel.io"]?.pages ?? {}).length, "reported:", st["clf:quietpixel.io"]?.reported);
console.log("unknown insights:", JSON.stringify(st.unknown ?? []));
console.log("sw warnings/errors:", errs.slice(0, 3));
const tabId = await sw.evaluate(async () => (await chrome.tabs.query({ url: "http://127.0.0.1/*" }))[0]?.id);
const popup = await ctx.newPage();
await popup.goto(`chrome-extension://${extId}/popup.html?tab=${tabId}`);
await popup.waitForTimeout(800);
const txt = await popup.locator("[data-testid=unknown]").innerText().catch(() => "MISSING");
console.log("popup:", txt.split(String.fromCharCode(10)).join(" | "));
await ctx.close(); site.close();
