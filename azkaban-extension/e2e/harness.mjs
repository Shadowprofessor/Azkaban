// Loads the built extension into Chromium and serves e2e/site on 127.0.0.1.
import { chromium } from "@playwright/test";
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
export const EXT = path.join(root, ".output", "chrome-mv3");

export async function startSite(port = 4777) {
  const dir = path.join(root, "e2e", "site");
  const srv = http.createServer((req, res) => {
    const f = path.join(dir, req.url === "/" ? "index.html" : req.url.split("?")[0]);
    if (!f.startsWith(dir) || !fs.existsSync(f)) { res.writeHead(404); return res.end(); }
    res.writeHead(200, { "content-type": f.endsWith(".html") ? "text/html" : "text/plain" });
    fs.createReadStream(f).pipe(res);
  });
  await new Promise((r) => srv.listen(port, "127.0.0.1", r));
  return { url: `http://127.0.0.1:${port}/`, close: () => srv.close() };
}

export async function launch() {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), "azk-ext-"));
  const ctx = await chromium.launchPersistentContext(dir, {
    channel: "chromium",
    headless: true,
    args: [`--disable-extensions-except=${EXT}`, `--load-extension=${EXT}`],
  });
  let [sw] = ctx.serviceWorkers();
  if (!sw) sw = await ctx.waitForEvent("serviceworker");
  const extId = new URL(sw.url()).host;
  return { ctx, sw, extId };
}
