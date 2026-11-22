import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Loopback only, on purpose. The agent's WebSocket accepts localhost origins only
// (azkaban_agent/wsserver.LOCAL_ORIGINS), and serving a privacy audit UI to the whole
// LAN would be a poor default for a tool whose premise is that nothing leaves the machine.
//
// Two backends sit behind this site:
//   ws://127.0.0.1:8787   azkaban-agent  live capture, flows, score, verdicts (direct socket)
//   http://127.0.0.1:8765 ghostprint     account links, breach scan, site checks (via /api)
// /api is proxied so the website's fetch('/api/...') calls reach ghostprint. changeOrigin
// makes the Host header match what ghostprint's Host check expects; the Origin header is
// left alone and ghostprint admits 127.0.0.1:5173 through an explicit allowlist.
const GHOSTPRINT = 'http://127.0.0.1:8765';

export default defineConfig({
  plugins: [react()],
  server: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api': { target: GHOSTPRINT, changeOrigin: true } },
  },
  preview: {
    host: '127.0.0.1', port: 5173, strictPort: true,
    proxy: { '/api': { target: GHOSTPRINT, changeOrigin: true } },
  },
});
