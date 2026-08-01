/**
 * Mock data matching the API contract — used when PUBLIC_USE_MOCK=true so the
 * frontend is runnable & demoable without the backend. Deterministic-ish so the
 * UI looks alive but stable.
 */
import type {
  AirportDetail,
  AirportOption,
  CarrierOption,
  Health,
  LivePositions,
  MetaOptions,
  PredictRequest,
  PredictResponse,
  RouteReliability
} from './api';
import { riskBandFor } from './api';

const DATA_VERSION = '2025-06-16';

export const MOCK_AIRPORTS: AirportOption[] = [
  { iata: 'ATL', name: 'Hartsfield-Jackson Atlanta Intl', lat: 33.6367, lon: -84.4281 },
  { iata: 'ORD', name: "Chicago O'Hare Intl", lat: 41.9786, lon: -87.9048 },
  { iata: 'DFW', name: 'Dallas/Fort Worth Intl', lat: 32.8968, lon: -97.038 },
  { iata: 'DEN', name: 'Denver Intl', lat: 39.8617, lon: -104.6731 },
  { iata: 'LAX', name: 'Los Angeles Intl', lat: 33.9425, lon: -118.4081 },
  { iata: 'JFK', name: 'John F. Kennedy Intl', lat: 40.6398, lon: -73.7789 },
  { iata: 'SFO', name: 'San Francisco Intl', lat: 37.619, lon: -122.3748 },
  { iata: 'SEA', name: 'Seattle-Tacoma Intl', lat: 47.449, lon: -122.3088 },
  { iata: 'LAS', name: 'Harry Reid Intl', lat: 36.084, lon: -115.1537 },
  { iata: 'MCO', name: 'Orlando Intl', lat: 28.4294, lon: -81.309 },
  { iata: 'EWR', name: 'Newark Liberty Intl', lat: 40.6925, lon: -74.1687 },
  { iata: 'BOS', name: 'Logan Intl', lat: 42.3656, lon: -71.0096 },
  { iata: 'MIA', name: 'Miami Intl', lat: 25.7959, lon: -80.287 },
  { iata: 'PHX', name: 'Phoenix Sky Harbor Intl', lat: 33.4342, lon: -112.0116 },
  { iata: 'IAH', name: 'George Bush Intercontinental', lat: 29.9902, lon: -95.3368 }
];

export const MOCK_CARRIERS: CarrierOption[] = [
  { code: 'DL', name: 'Delta Air Lines' },
  { code: 'AA', name: 'American Airlines' },
  { code: 'UA', name: 'United Airlines' },
  { code: 'WN', name: 'Southwest Airlines' },
  { code: 'B6', name: 'JetBlue Airways' },
  { code: 'AS', name: 'Alaska Airlines' },
  { code: 'NK', name: 'Spirit Airlines' },
  { code: 'F9', name: 'Frontier Airlines' }
];

export function health(): Health {
  return { status: 'ok', model_loaded: true, gold_loaded: true, data_version: DATA_VERSION };
}

export function options(): MetaOptions {
  return {
    airports: MOCK_AIRPORTS,
    carriers: MOCK_CARRIERS,
    example_presets: [
      { origin: 'ATL', dest: 'ORD', carrier: 'DL', day_of_week: 5, dep_hour: 17 },
      { origin: 'SFO', dest: 'JFK', carrier: 'B6', day_of_week: 1, dep_hour: 7 },
      { origin: 'DEN', dest: 'LAS', carrier: 'WN', day_of_week: 6, dep_hour: 20 },
      { origin: 'EWR', dest: 'MIA', carrier: 'UA', day_of_week: 4, dep_hour: 18 }
    ]
  };
}

// Cheap deterministic hash so identical inputs give identical predictions.
function hash(s: string): number {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0) / 0xffffffff;
}

export function predict(body: PredictRequest): PredictResponse {
  const seed = hash(`${body.origin}-${body.dest}-${body.carrier}-${body.dep_hour}`);
  // Rush-hour and a touch of randomness drive the probability.
  const rush = body.dep_hour >= 16 && body.dep_hour <= 20 ? 0.12 : 0;
  const p = Math.min(0.92, Math.max(0.05, 0.18 + seed * 0.4 + rush));
  const baseline = Math.max(0.05, p - 0.06 - seed * 0.05);
  const gust = 18 + seed * 30;
  return {
    delay_probability: round(p),
    risk_band: riskBandFor(p),
    baseline_probability: round(baseline),
    beats_baseline: p < baseline,
    calibrated: true,
    top_factors: [
      { feature: 'origin_wind_gusts', value: round(gust, 1), contribution: round(0.04 + seed * 0.06), direction: 'increases' },
      { feature: 'dep_hour', value: body.dep_hour, contribution: round(rush > 0 ? 0.05 : 0.01), direction: 'increases' },
      { feature: 'route_hist_delay_rate', value: round(baseline), contribution: round(0.02 + seed * 0.03), direction: 'increases' },
      { feature: 'carrier_hist_delay_rate', value: round(0.12 + seed * 0.1), contribution: round(-(0.02 + seed * 0.03)), direction: 'decreases' },
      { feature: 'origin_precip_mm', value: round(seed * 3, 1), contribution: round(-(0.01 + seed * 0.02)), direction: 'decreases' }
    ],
    weather_summary: {
      origin: { temp_c: Math.round(12 + seed * 18), precip_mm: round(seed * 3, 1), wind_gusts: round(gust, 1) },
      dest: { temp_c: Math.round(10 + (1 - seed) * 16), precip_mm: round((1 - seed) * 2.5, 1), wind_gusts: round(15 + (1 - seed) * 20, 1) }
    },
    data_version: DATA_VERSION
  };
}

let mockTick = 0;
export function livePositions(): LivePositions {
  mockTick++;
  const count = 480;
  const aircraft = [];
  for (let i = 0; i < count; i++) {
    const r = hash(`ac-${i}`);
    const r2 = hash(`ac2-${i}`);
    // Drift longitude slowly each poll so the map visibly updates.
    const drift = ((mockTick * (0.01 + r * 0.02)) % 1) * 0.6;
    aircraft.push({
      icao24: (0x100000 + i).toString(16),
      callsign: ['UAL', 'AAL', 'DAL', 'SWA', 'JBU'][i % 5] + (1000 + Math.floor(r2 * 8005)),
      lat: round(25 + r * 23, 4),
      lon: round(-123 + r2 * 56 + drift, 4),
      altitude: round(1500 + r * 11000, 1),
      velocity: round(120 + r2 * 130, 1),
      heading: round((r * 360 + mockTick * 3) % 360, 1),
      on_ground: r < 0.06
    });
  }
  return {
    as_of: Math.floor(Date.now() / 1000),
    stale_seconds: Math.floor(hash(`stale-${mockTick}`) * 20),
    source: 'sample',
    count,
    aircraft
  };
}

export function airport(iata: string): AirportDetail {
  const meta = MOCK_AIRPORTS.find((a) => a.iata === iata) ?? MOCK_AIRPORTS[0];
  const seed = hash(iata);
  const by_hour = Array.from({ length: 24 }, (_, h) => {
    const peak = h >= 16 && h <= 20 ? 0.12 : h <= 5 ? -0.05 : 0;
    return { hour: h, delay_rate: round(Math.max(0.03, 0.14 + seed * 0.1 + peak + Math.sin(h) * 0.02)) };
  });
  const dests = MOCK_AIRPORTS.filter((a) => a.iata !== iata).slice(0, 5);
  const worst_routes = dests
    .map((d) => ({ dest: d.iata, delay_rate: round(0.2 + hash(iata + d.iata) * 0.25) }))
    .sort((a, b) => b.delay_rate - a.delay_rate)
    .slice(0, 4);
  const nearby = Math.round(8 + seed * 60);
  return {
    iata: meta.iata,
    name: meta.name,
    lat: meta.lat,
    lon: meta.lon,
    historical: {
      overall_delay_rate: round(0.16 + seed * 0.12),
      by_hour,
      worst_routes
    },
    live_congestion: {
      aircraft_nearby: nearby,
      level: nearby > 45 ? 'high' : nearby > 22 ? 'moderate' : 'low'
    }
  };
}

export function routeReliability(origin: string, dest: string): RouteReliability {
  const seed = hash(origin + dest);
  const rate = round(0.16 + seed * 0.22);
  return {
    origin,
    dest,
    delay_rate: rate,
    flights: Math.round(4000 + seed * 18005),
    avg_delay_min: round(9 + seed * 22, 1),
    by_carrier: MOCK_CARRIERS.slice(0, 4).map((c) => ({
      carrier: c.code,
      delay_rate: round(Math.max(0.05, rate + (hash(origin + dest + c.code) - 0.5) * 0.12))
    }))
  };
}

function round(n: number, dp = 2): number {
  const f = 10 ** dp;
  return Math.round(n * f) / f;
}
