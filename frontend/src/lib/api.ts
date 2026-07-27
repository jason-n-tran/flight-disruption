/**
 * Typed API client mirroring shared/flight_contracts/api_contract.md EXACTLY.
 * Every shape here matches an endpoint in that contract; treat changes as breaking.
 */
import { PUBLIC_API_BASE, PUBLIC_USE_MOCK } from '$env/static/public';
import * as mock from './mock';

/**
 * Normalize the configured API base:
 *  - default to localhost for dev when unset
 *  - if a host was given without a scheme (e.g. "api.example.com"), prepend
 *    https:// so it's treated as ABSOLUTE — otherwise the browser resolves it
 *    relative to the page origin (a common, confusing misconfig)
 *  - strip any trailing slash so `${base}${path}` never double-slashes
 */
function normalizeApiBase(raw: string | undefined): string {
  let base = (raw ?? '').trim();
  if (!base) return 'http://localhost:8005';
  if (!/^https?:\/\//i.test(base)) base = `https://${base}`;
  return base.replace(/\/+$/, '');
}

export const API_BASE: string = normalizeApiBase(PUBLIC_API_BASE);
export const USE_MOCK: boolean = String(PUBLIC_USE_MOCK).toLowerCase() === 'true';

// ---------------------------------------------------------------------------
// Contract types
// ---------------------------------------------------------------------------

export type RiskBand = 'low' | 'moderate' | 'high';
export type LiveSource = 'live' | 'cached' | 'sample';

export interface Health {
  status: string;
  model_loaded: boolean;
  gold_loaded: boolean;
  data_version: string;
}

export interface AirportOption {
  iata: string;
  name: string;
  lat: number;
  lon: number;
}

export interface CarrierOption {
  code: string;
  name: string;
}

export interface ExamplePreset {
  origin: string;
  dest: string;
  carrier: string;
  day_of_week: number;
  dep_hour: number;
}

export interface MetaOptions {
  airports: AirportOption[];
  carriers: CarrierOption[];
  example_presets: ExamplePreset[];
}

export interface PredictRequest {
  origin: string;
  dest: string;
  carrier: string;
  date: string; // YYYY-MM-DD
  dep_hour: number;
}

export interface TopFactor {
  feature: string;
  value: number;
  contribution: number;
  direction: 'increases' | 'decreases';
}

export interface WeatherPoint {
  temp_c: number;
  precip_mm: number;
  wind_gusts: number;
}

export interface PredictResponse {
  delay_probability: number;
  risk_band: RiskBand;
  baseline_probability: number;
  beats_baseline: boolean;
  calibrated: boolean;
  top_factors: TopFactor[];
  weather_summary: { origin: WeatherPoint; dest: WeatherPoint };
  data_version: string;
}

export interface Aircraft {
  icao24: string;
  callsign: string;
  lat: number;
  lon: number;
  altitude: number;
  velocity: number;
  heading: number;
  on_ground: boolean;
}

export interface LivePositions {
  as_of: number;
  stale_seconds: number;
  source: LiveSource;
  count: number;
  aircraft: Aircraft[];
}

export interface HourDelay {
  hour: number;
  delay_rate: number;
}

export interface WorstRoute {
  dest: string;
  delay_rate: number;
}

export interface AirportDetail {
  iata: string;
  name: string;
  lat: number;
  lon: number;
  historical: {
    overall_delay_rate: number;
    by_hour: HourDelay[];
    worst_routes: WorstRoute[];
  };
  live_congestion: {
    aircraft_nearby: number;
    level: 'low' | 'moderate' | 'high';
  };
}

export interface RouteReliability {
  origin: string;
  dest: string;
  delay_rate: number;
  flights: number;
  avg_delay_min: number;
  by_carrier: { carrier: string; delay_rate: number }[];
}

// ---------------------------------------------------------------------------
// Risk band helpers (shared constant in the contract)
// ---------------------------------------------------------------------------

export function riskBandFor(p: number): RiskBand {
  if (p < 0.2) return 'low';
  if (p < 0.45) return 'moderate';
  return 'high';
}

// Codified avionics caution language: engaged / caution / warning.
export const RISK_COLORS: Record<RiskBand, string> = {
  low: '#2fe6a4',
  moderate: '#ffb12e',
  high: '#ff5247'
};

// ---------------------------------------------------------------------------
// Fetch client
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(
  path: string,
  init?: RequestInit,
  timeoutMs = 12_000
): Promise<T> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...init,
      signal: controller.signal,
      headers: {
        Accept: 'application/json',
        ...(init?.body ? { 'Content-Type': 'application/json' } : {}),
        ...(init?.headers ?? {})
      }
    });
    if (!res.ok) {
      throw new ApiError(`Request to ${path} failed`, res.status);
    }
    return (await res.json()) as T;
  } catch (err) {
    if (err instanceof ApiError) throw err;
    const msg = err instanceof Error ? err.message : 'network error';
    throw new ApiError(`Cannot reach API at ${API_BASE}${path}: ${msg}`, 0);
  } finally {
    clearTimeout(timer);
  }
}

// ---------------------------------------------------------------------------
// Endpoint methods. Each transparently serves mock data when PUBLIC_USE_MOCK.
// ---------------------------------------------------------------------------

export const api = {
  health(): Promise<Health> {
    if (USE_MOCK) return Promise.resolve(mock.health());
    return request<Health>('/health');
  },

  options(): Promise<MetaOptions> {
    if (USE_MOCK) return Promise.resolve(mock.options());
    return request<MetaOptions>('/api/meta/options');
  },

  predict(body: PredictRequest): Promise<PredictResponse> {
    if (USE_MOCK) return Promise.resolve(mock.predict(body));
    return request<PredictResponse>('/api/predict', {
      method: 'POST',
      body: JSON.stringify(body)
    });
  },

  livePositions(): Promise<LivePositions> {
    if (USE_MOCK) return Promise.resolve(mock.livePositions());
    return request<LivePositions>('/api/live/positions');
  },

  airport(iata: string): Promise<AirportDetail> {
    if (USE_MOCK) return Promise.resolve(mock.airport(iata));
    return request<AirportDetail>(`/api/airport/${encodeURIComponent(iata)}`);
  },

  routeReliability(origin: string, dest: string): Promise<RouteReliability> {
    if (USE_MOCK) return Promise.resolve(mock.routeReliability(origin, dest));
    const qs = new URLSearchParams({ origin, dest }).toString();
    return request<RouteReliability>(`/api/reliability/route?${qs}`);
  }
};
