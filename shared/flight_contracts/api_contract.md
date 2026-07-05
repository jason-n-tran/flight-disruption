# API Contract — Flight Disruption Platform

The FastAPI serving app (`serving/`) and the SvelteKit frontend (`frontend/`)
**must** agree on these shapes. This is the interface boundary; treat changes
as breaking.

Base URL (local): `http://localhost:8005`
All responses JSON. CORS enabled for the frontend origin.

---

## `GET /health`
```json
{ "status": "ok", "model_loaded": true, "gold_loaded": true, "data_version": "2025-06-16" }
```

## `GET /api/meta/options`
Dropdown data for the route+time builder (from gold `dim_airports` + known routes).
```json
{
  "airports": [
    { "iata": "ATL", "name": "Hartsfield-Jackson Atlanta Intl", "lat": 33.6367, "lon": -84.4281 }
  ],
  "carriers": [ { "code": "DL", "name": "Delta Air Lines" } ],
  "example_presets": [
    { "origin": "ATL", "dest": "ORD", "carrier": "DL", "day_of_week": 5, "dep_hour": 17 }
  ]
}
```

## `POST /api/predict`
Risk lookup. Inputs are all pre-departure (leakage-safe by construction).
Request:
```json
{
  "origin": "ATL",
  "dest": "ORD",
  "carrier": "DL",
  "date": "2026-06-20",
  "dep_hour": 17
}
```
Response:
```json
{
  "delay_probability": 0.34,
  "risk_band": "moderate",            // low <0.2, moderate 0.2-0.45, high >0.45
  "baseline_probability": 0.22,        // historical base rate for this route
  "beats_baseline": true,
  "calibrated": true,
  "top_factors": [                     // live SHAP, signed contributions
    { "feature": "origin_wind_gusts", "value": 41.2, "contribution": 0.08, "direction": "increases" },
    { "feature": "dep_hour", "value": 17, "contribution": 0.05, "direction": "increases" },
    { "feature": "carrier_hist_delay_rate", "value": 0.19, "contribution": -0.03, "direction": "decreases" }
  ],
  "weather_summary": { "origin": { "temp_c": 22, "precip_mm": 0, "wind_gusts": 41.2 },
                       "dest":   { "temp_c": 18, "precip_mm": 1.2, "wind_gusts": 22.0 } },
  "data_version": "2025-06-16"
}
```

## `GET /api/live/positions`
Live aircraft positions (from Valkey cache, OpenSky-fed). Never empty (cache/sample fallback).
```json
{
  "as_of": 1781639355,
  "stale_seconds": 12,
  "source": "live",                    // "live" | "cached" | "sample"
  "count": 6821,
  "aircraft": [
    { "icao24": "ab1644", "callsign": "UAL1091", "lat": 29.33, "lon": -96.42,
      "altitude": 6606.5, "velocity": 209.6, "heading": 43.6, "on_ground": false }
  ]
}
```

## `GET /api/airport/{iata}`
Airport bridge view (fuses live congestion + historical reliability).
```json
{
  "iata": "ATL",
  "name": "Hartsfield-Jackson Atlanta Intl",
  "lat": 33.6367, "lon": -84.4281,
  "historical": {
    "overall_delay_rate": 0.21,
    "by_hour": [ { "hour": 0, "delay_rate": 0.08 } ],
    "worst_routes": [ { "dest": "EWR", "delay_rate": 0.39 } ]
  },
  "live_congestion": { "aircraft_nearby": 47, "level": "high" }  // from live feed
}
```

## `GET /api/reliability/route?origin=ATL&dest=ORD`
Reliability explorer.
```json
{ "origin": "ATL", "dest": "ORD", "delay_rate": 0.27, "flights": 14233, "avg_delay_min": 18.4,
  "by_carrier": [ { "carrier": "DL", "delay_rate": 0.24 } ] }
```

---

### Risk bands (shared constant)
- `low`: probability < 0.20
- `moderate`: 0.20 ≤ probability < 0.45
- `high`: probability ≥ 0.45
