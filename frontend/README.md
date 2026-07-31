# Flight Disruption Intelligence — Frontend

The user-facing live demo for the Flight Disruption Intelligence Platform. A single,
highly-interactive SvelteKit app with three connected, fused views:

1. **Live aircraft map** — MapLibre GL map of the continental US. Aircraft render as a
   single GeoJSON symbol layer (rotated by `heading`), so thousands of planes stay smooth.
   Polls `GET /api/live/positions` every ~30s with an *as-of / stale / source* indicator.
2. **Risk lookup** — a route + time builder (`POST /api/predict`) that shows an explainable,
   probabilistic delay-risk estimate: a banded gauge, baseline comparison, calibration note,
   signed SHAP factor bars, and a weather summary.
3. **Reliability explorer + airport bridge** — clicking an airport on the map opens a panel
   (`GET /api/airport/{iata}`) fusing **live congestion** with **historical reliability**.
   A route lookup (`GET /api/reliability/route`) adds carrier-level breakdowns.

Built as a **fully static** bundle (`@sveltejs/adapter-static`, SPA fallback) so it deploys
to **Cloudflare Pages free tier** with no SSR.

## Stack

- SvelteKit (Svelte 5 runes) + TypeScript
- `@sveltejs/adapter-static` (`fallback: index.html` → SPA)
- MapLibre GL (open-source, **no API token**), OpenStreetMap raster tiles
- **Charts: hand-rolled SVG/CSS bars** (`src/lib/components/BarChart.svelte`,
  `FactorBars.svelte`) — no chart library, keeping the static bundle lean.

## Environment

Configured via `$env/static/public` (inlined at build time). Copy `.env.example` to `.env`:

| Var               | Default                 | Meaning                                              |
| ----------------- | ----------------------- | ---------------------------------------------------- |
| `PUBLIC_API_BASE` | `http://localhost:8005` | Base URL of the FastAPI backend (no trailing slash). |
| `PUBLIC_USE_MOCK` | `false`                 | `true` serves bundled mock data — no backend needed. |

> `PUBLIC_*` vars are baked in at build time. Rebuild to change them.

## Develop

```bash
npm install
cp .env.example .env      # optionally set PUBLIC_USE_MOCK=true
npm run dev               # http://localhost:5173
```

To run with **no backend**, set `PUBLIC_USE_MOCK=true` — the app serves realistic sample data
matching the API contract (`src/lib/mock.ts`). The demo never shows a broken/empty state:
loading spinners, friendly empty states, and an offline banner keep it credible.

## Build (static)

```bash
npm run build     # outputs to ./build
npm run preview   # serve the static build locally
```

The contents of `build/` are the deployable static site.

## Deploy — Cloudflare Pages

- **Build command:** `npm run build`
- **Build output directory:** `build`
- **Environment variables:** set `PUBLIC_API_BASE` (your FastAPI URL) and optionally
  `PUBLIC_USE_MOCK`.
- No SSR / no Functions required — this is a pure static SPA (adapter-static with
  `fallback: index.html` handles client-side routing).

## Deploy — Docker (nginx)

A multi-stage `Dockerfile` builds the static site and serves it with `nginx:alpine` on port 80,
with SPA fallback (`nginx.conf`). The base compose passes `PUBLIC_API_BASE` as a build arg.

```bash
docker build -t flight-frontend --build-arg PUBLIC_API_BASE=https://api.example.com .
docker run -p 8080:80 flight-frontend   # http://localhost:8080
```

## API contract

All shapes mirror `shared/flight_contracts/api_contract.md`. Types and a typed fetch client
(with timeouts and graceful errors) live in `src/lib/api.ts`.

## Project layout

```
src/
  app.css                      global theme (dark, aviation-ish)
  routes/+page.svelte          app shell: header, tabs, offline banner
  routes/+layout.ts            prerender + ssr:false (static SPA)
  lib/
    api.ts                     contract types + typed fetch client + mock toggle
    mock.ts                    sample data matching the contract
    stores.svelte.ts           options + health stores (runes)
    format.ts                  presentation helpers
    components/                LiveMap, AirportPanel, RiskGauge, FactorBars,
                               BarChart, SourceBadge, Banner, Spinner
    views/                     LiveMapView, RiskLookup, Reliability
```
