import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

// Loopback only, on purpose. The agent's WebSocket accepts localhost origins only
// (azkaban_agent/wsserver.LOCAL_ORIGINS), and serving a privacy audit UI to the whole
// LAN would be a poor default for a tool whose premise is that nothing leaves the machine.
export default defineConfig({
  plugins: [react()],
  server: { host: '127.0.0.1', port: 5173, strictPort: true },
  preview: { host: '127.0.0.1', port: 5173, strictPort: true },
});
