/** Small presentation helpers shared across views. */

export function pct(n: number, dp = 0): string {
  return `${(n * 100).toFixed(dp)}%`;
}

export function num(n: number): string {
  return n.toLocaleString('en-US');
}

const HOUR_LABELS = Array.from({ length: 24 }, (_, h) => {
  const am = h < 12;
  const base = h % 12 === 0 ? 12 : h % 12;
  return `${base}${am ? 'a' : 'p'}`;
});

export function hourLabel(h: number): string {
  return HOUR_LABELS[((h % 24) + 24) % 24];
}

const DOW = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];
export function dowLabel(d: number): string {
  return DOW[((d % 7) + 7) % 7] ?? '';
}

/** Turn snake_case feature names into a readable label. */
export function featureLabel(f: string): string {
  return f
    .replace(/_/g, ' ')
    .replace(/\bhist\b/, 'historical')
    .replace(/\bdep\b/, 'departure')
    .replace(/\bprecip\b/, 'precipitation')
    .replace(/\bmm\b/, '(mm)')
    .replace(/\bc\b/, '(°C)')
    .replace(/\b\w/g, (c) => c.toUpperCase());
}

/** Next Friday in YYYY-MM-DD, used as a sensible default date. */
export function defaultDate(): string {
  const d = new Date();
  d.setDate(d.getDate() + ((5 - d.getDay() + 7) % 7 || 7));
  return d.toISOString().slice(0, 10);
}

/** Zero-padded instrument-style hour label, e.g. 7 -> "0700". */
export function hhmm(h: number): string {
  return `${String(((h % 24) + 24) % 24).padStart(2, '0')}00`;
}

/**
 * Weather in METAR-flavoured shorthand for the cockpit voice:
 *   "07°C · CALM · DRY"  /  "12°C · G24 · RA 3.0mm"
 * Coded and scannable, true to the aviation subject — same numbers, ops dialect.
 */
export function metar(w: { temp_c: number; precip_mm: number; wind_gusts: number }): string {
  const t = `${Math.round(w.temp_c)}°C`;
  const wind = w.wind_gusts >= 1 ? `G${Math.round(w.wind_gusts)}` : 'CALM';
  const precip = w.precip_mm >= 0.1 ? `RA ${w.precip_mm.toFixed(1)}mm` : 'DRY';
  return `${t} · ${wind} · ${precip}`;
}
