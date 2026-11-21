import { defineConfig } from "wxt";

// Chromium MV3 (Chrome / Edge / Brave / Opera).
export default defineConfig({
  manifest: {
    name: "Azkaban — The Trace",
    description: "See which trackers (Dementors) your browser talks to, what they take, and block them. Nothing leaves your machine.",
    permissions: [
      "webRequest",
      "declarativeNetRequest",
      "declarativeNetRequestFeedback",
      "cookies",
      "storage",
      "tabs",
      "notifications",
      "scripting",
      "alarms",
    ],
    host_permissions: ["<all_urls>"],
    // Browser-enforced privacy: extension pages may only connect to the local agent / Ollama.
    content_security_policy: {
      extension_pages:
        "script-src 'self'; object-src 'self'; connect-src 'self' ws://localhost:8787 ws://127.0.0.1:8787 http://localhost:11434 http://127.0.0.1:11434;",
    },
    action: { default_title: "Azkaban" },
  },
});
