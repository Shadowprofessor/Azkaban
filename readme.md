# GhostPrint frontend

A responsive React frontend for the GhostPrint print studio. The frontend can run on one laptop while the backend runs on another laptop, using a VS Code forwarded port URL.

## Run locally

Install Node.js, then from this folder run:

```powershell
npm install
npm run dev
```

Vite listens on `0.0.0.0:5173`, so the dev server can also be exposed through VS Code Port Forwarding when needed.

## Connect a backend on another laptop

1. Start the backend on its laptop, bound to `0.0.0.0` on its API port (for example `8000`).
2. Forward that port in VS Code's **Ports** panel and copy its HTTPS forwarded address.
3. In GhostPrint, open **Connect backend** in the footer and paste that address.
4. Choose **Check connection**. The frontend checks `GET {backend-url}/health` and saves the URL in this browser.

The backend's health endpoint must allow requests from the origin hosting this frontend. Configure CORS for the frontend origin and accept the app's JSON request patterns as the API is completed. Do not embed API secrets in `.env` values exposed with the `VITE_` prefix.

The starter connection setting can also be set before launching Vite:

```env
VITE_API_BASE_URL=https://your-server-8000.app.github.dev
```

Copy `.env.example` to `.env.local` for a per-laptop value; keep `.env.local` out of source control. Since VS Code forwarded URLs can change between sessions and laptops, the in-app setting is convenient for development.

## Frontend/backend seam

- Backend URL: `VITE_API_BASE_URL` at build time, overridden by the saved URL entered in the app.
- Connection check: `GET /health`.
- Print-job upload/queue integration is intentionally ready to connect once the backend endpoints and payload contract are defined. The current queue, sample records, and upload progress are frontend demo state.
- VS Code forwarding does not define API routes or CORS behavior; those must be provided by the server.
