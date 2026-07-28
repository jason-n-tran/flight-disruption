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
