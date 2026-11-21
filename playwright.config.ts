import { defineConfig } from "@playwright/test";

// End-to-end: real agent replay + production dashboard build.
export default defineConfig({
  testDir: "e2e",
  timeout: 90_000,
  use: { baseURL: "http://localhost:3000", viewport: { width: 1400, height: 900 } },
  webServer: [
    {
      command: "python -m azkaban_agent replay azkaban-agent/demo/demo.azk --speed 8x --wait 30",
      port: 8787,
      reuseExistingServer: false,
      timeout: 60_000,
    },
    { command: "npx next start -p 3000", port: 3000, reuseExistingServer: true, timeout: 60_000 },
  ],
});
