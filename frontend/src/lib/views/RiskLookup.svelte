<script lang="ts">
  import { api, type ExamplePreset, type PredictRequest, type PredictResponse } from '$lib/api';
  import { optionsStore } from '$lib/stores.svelte';
  import { defaultDate, dowLabel, hhmm, hourLabel, metar, pct } from '$lib/format';
  import RiskGauge from '$lib/components/RiskGauge.svelte';
  import FactorBars from '$lib/components/FactorBars.svelte';
  import RouteTrack from '$lib/components/RouteTrack.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import Banner from '$lib/components/Banner.svelte';

  let origin = $state('ATL');
  let dest = $state('ORD');
  let carrier = $state('DL');
  let date = $state(defaultDate());
  let depHour = $state(17);

  let result = $state<PredictResponse | null>(null);
  // Remember what was scored, so the result strip never disagrees with the form.
  let scored = $state<{ origin: string; dest: string; carrier: string; depHour: number } | null>(
    null
  );
  let loading = $state(false);
  let error = $state<string | null>(null);

  const opts = $derived(optionsStore.data);

  function applyPreset(p: ExamplePreset) {
    origin = p.origin;
    dest = p.dest;
    carrier = p.carrier;
    depHour = p.dep_hour;
    submit();
  }

  async function submit() {
    if (origin === dest) {
      error = 'Origin and destination must differ — pick two airports.';
      return;
    }
    loading = true;
    error = null;
    const body: PredictRequest = { origin, dest, carrier, date, dep_hour: depHour };
    try {
      result = await api.predict(body);
      scored = { origin, dest, carrier, depHour };
    } catch (e) {
      error = e instanceof Error ? e.message : 'Could not score this flight.';
    } finally {
      loading = false;
    }
  }

  function carrierName(code: string): string {
    return opts?.carriers.find((c) => c.code === code)?.name ?? code;
  }
</script>

<div class="grid">
  <!-- Flight plan input -->
  <section class="panel build">
    <p class="eyebrow">Build a flight plan</p>
    <p class="lede">
      Every field is known before pushback — scheduled time, route, operator. The model never
      reads after-the-fact data, so the score is honest about what's knowable at the gate.
    </p>

    {#if opts?.example_presets?.length}
      <div class="presets" role="group" aria-label="Example flights">
        <span class="eyebrow tiny">Quick load</span>
        <div class="chiprow">
          {#each opts.example_presets as p (p.origin + p.dest + p.dep_hour)}
            <button class="chip mono" onclick={() => applyPreset(p)}>
              {p.origin}–{p.dest} {dowLabel(p.day_of_week)} {hhmm(p.dep_hour)}
            </button>
          {/each}
        </div>
      </div>
    {/if}

    <form
      onsubmit={(e) => {
        e.preventDefault();
        submit();
      }}
    >
      <div class="field">
        <label for="origin">Departing</label>
        <select id="origin" bind:value={origin}>
          {#each opts?.airports ?? [] as a (a.iata)}
            <option value={a.iata}>{a.iata} — {a.name}</option>
          {/each}
        </select>
      </div>
      <div class="field">
        <label for="dest">Arriving</label>
        <select id="dest" bind:value={dest}>
          {#each opts?.airports ?? [] as a (a.iata)}
            <option value={a.iata}>{a.iata} — {a.name}</option>
          {/each}
        </select>
      </div>
      <div class="field">
        <label for="carrier">Operator</label>
        <select id="carrier" bind:value={carrier}>
          {#each opts?.carriers ?? [] as c (c.code)}
            <option value={c.code}>{c.code} — {c.name}</option>
          {/each}
        </select>
      </div>
      <div class="row2">
        <div class="field">
          <label for="date">Date</label>
          <input id="date" type="date" bind:value={date} />
        </div>
        <div class="field">
          <label for="hour">Scheduled out</label>
          <select id="hour" bind:value={depHour}>
            {#each Array(24) as _, h (h)}
              <option value={h}>{hhmm(h)} · {hourLabel(h)}</option>
            {/each}
          </select>
        </div>
      </div>
      <button class="run" type="submit" disabled={loading}>
        {loading ? 'Scoring…' : 'Score this flight'}
      </button>
    </form>

    {#if optionsStore.error}
      <Banner kind="warn" message="Couldn't load the airport and operator lists. Reconnect to the API and reload." />
    {/if}
  </section>

  <!-- Result: a flight strip -->
  <section class="panel strip" aria-live="polite">
    {#if loading}
      <div class="center"><Spinner label="Scoring the flight plan…" /></div>
    {:else if error}
      <Banner kind="error" message={error} />
    {:else if result && scored}
      <header class="strip-head">
        <RouteTrack
          origin={scored.origin}
          dest={scored.dest}
          progress={result.delay_probability}
          label="DELAY RISK ALONG COURSE"
        />
        <p class="route-meta mono">
          {carrierName(scored.carrier)} · OUT {hhmm(scored.depHour)} · {date}
        </p>
      </header>

      <RiskGauge
        probability={result.delay_probability}
        band={result.risk_band}
        baseline={result.baseline_probability}
      />

      <div class="tags">
        <span class="tag" class:ok={result.beats_baseline} class:warn={!result.beats_baseline}>
          {result.beats_baseline ? 'Sharper than the base rate' : 'No better than base rate'}
          · base {pct(result.baseline_probability)}
        </span>
        {#if result.calibrated}
          <span class="tag info" title="Probabilities are calibrated against held-out 2025 flights.">
            Calibrated
          </span>
        {/if}
        <span class="tag mono dim">DATA {result.data_version}</span>
      </div>

      <div class="block">
        <p class="eyebrow">What's driving the number</p>
        <FactorBars factors={result.top_factors} />
        <p class="legend">
          <span class="sw warn"></span> raises risk
          <span class="sw ok"></span> lowers risk
        </p>
      </div>

      <div class="block">
        <p class="eyebrow">Weather along the route</p>
        <div class="wx">
          <div class="wx-cell">
            <span class="wx-fix mono">{scored.origin}</span>
            <span class="wx-read mono">{metar(result.weather_summary.origin)}</span>
          </div>
          <div class="wx-cell">
            <span class="wx-fix mono">{scored.dest}</span>
            <span class="wx-read mono">{metar(result.weather_summary.dest)}</span>
          </div>
        </div>
      </div>

      <p class="disclaimer">
        A probability of a 15-minute-plus departure delay — not a guarantee. Real outcomes turn on
        crew, aircraft routing, and ATC flow the model can't see at the gate.
      </p>
    {:else}
      <div class="center empty">
        <RouteTrack origin="ATL" dest="ORD" progress={0.34} />
        <p>Build a plan or quick-load one to read its delay risk, the conditions behind it, and the weather along the way.</p>
      </div>
    {/if}
  </section>
</div>

<style>
  .grid {
    display: grid;
    grid-template-columns: minmax(290px, 360px) 1fr;
    gap: 1rem;
    align-items: start;
  }
  @media (max-width: 880px) {
    .grid {
      grid-template-columns: 1fr;
    }
  }
  .panel {
    background: var(--panel);
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    padding: 1.1rem 1.15rem;
  }
  .lede {
    margin: 0.5rem 0 1.1rem;
    color: var(--muted);
    font-size: 0.84rem;
    line-height: 1.55;
  }
  .tiny {
    font-size: 0.6rem;
  }

  /* presets */
  .presets {
    margin-bottom: 1.1rem;
  }
  .chiprow {
    display: flex;
    flex-wrap: wrap;
    gap: 0.35rem;
    margin-top: 0.4rem;
  }
  .chip {
    background: var(--panel-2);
    border: 1px solid var(--line);
    color: var(--text);
    border-radius: var(--r-sharp);
    padding: 0.3rem 0.5rem;
    font-size: 0.72rem;
    letter-spacing: 0.04em;
    cursor: pointer;
    transition:
      border-color 0.15s,
      color 0.15s;
  }
  .chip:hover {
    border-color: var(--nav);
    color: var(--nav);
  }

  /* form */
  form {
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 0.28rem;
  }
  .row2 {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.7rem;
  }
  label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.64rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--faint);
  }
  select,
  input {
    background: var(--panel-2);
    border: 1px solid var(--line);
    color: var(--text);
    border-radius: var(--r);
    padding: 0.55rem 0.6rem;
    font-size: 0.88rem;
    font-family: inherit;
  }
  select:focus,
  input:focus {
    outline: 2px solid var(--nav);
    outline-offset: 0;
    border-color: var(--nav);
  }
  .run {
    margin-top: 0.3rem;
    background: var(--nav);
    color: #0a0e13;
    font-family: 'Saira Semi Condensed', sans-serif;
    font-weight: 700;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    border: none;
    border-radius: var(--r);
    padding: 0.7rem;
    font-size: 0.92rem;
    cursor: pointer;
    transition: filter 0.15s;
  }
  .run:hover:not(:disabled) {
    filter: brightness(1.12);
  }
  .run:disabled {
    opacity: 0.55;
    cursor: progress;
  }

  /* result strip */
  .strip {
    min-height: 340px;
    display: flex;
    flex-direction: column;
    gap: 1.05rem;
  }
  .strip-head {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    padding-bottom: 0.9rem;
    border-bottom: 1px solid var(--line);
  }
  .route-meta {
    margin: 0;
    font-size: 0.74rem;
    letter-spacing: 0.06em;
    color: var(--muted);
  }
  .tags {
    display: flex;
    flex-wrap: wrap;
    gap: 0.4rem;
  }
  .tag {
    font-size: 0.72rem;
    padding: 0.25rem 0.55rem;
    border-radius: var(--r-sharp);
    border: 1px solid var(--line);
    color: var(--muted);
    background: var(--panel-2);
  }
  .tag.ok {
    color: var(--ok);
    border-color: color-mix(in srgb, var(--ok) 40%, var(--line));
    background: color-mix(in srgb, var(--ok) 8%, transparent);
  }
  .tag.warn {
    color: var(--warn);
    border-color: color-mix(in srgb, var(--warn) 40%, var(--line));
    background: color-mix(in srgb, var(--warn) 8%, transparent);
  }
  .tag.info {
    color: var(--info);
    border-color: color-mix(in srgb, var(--info) 35%, var(--line));
  }
  .tag.dim {
    color: var(--faint);
  }
  .block {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }
  .legend {
    margin: 0.2rem 0 0;
    font-size: 0.7rem;
    color: var(--muted);
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }
  .sw {
    display: inline-block;
    width: 11px;
    height: 8px;
    border-radius: 1px;
  }
  .sw.warn {
    background: var(--warn);
  }
  .sw.ok {
    background: var(--ok);
    margin-left: 0.7rem;
  }
  .wx {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.6rem;
  }
  .wx-cell {
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-left: 2px solid var(--nav-dim);
    border-radius: var(--r);
    padding: 0.6rem 0.7rem;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  .wx-fix {
    font-size: 0.82rem;
    font-weight: 600;
    letter-spacing: 0.08em;
  }
  .wx-read {
    font-size: 0.76rem;
    color: var(--muted);
  }
  .disclaimer {
    margin: auto 0 0;
    font-size: 0.7rem;
    color: var(--faint);
    border-top: 1px solid var(--line);
    padding-top: 0.8rem;
    line-height: 1.55;
  }
  .center {
    margin: auto;
    width: 100%;
  }
  .empty {
    text-align: center;
    color: var(--muted);
    max-width: 420px;
    display: flex;
    flex-direction: column;
    gap: 1.1rem;
  }
  .empty p {
    margin: 0;
    font-size: 0.86rem;
    line-height: 1.55;
  }
</style>
