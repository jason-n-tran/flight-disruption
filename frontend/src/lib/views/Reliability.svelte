<script lang="ts">
  import { api, type RouteReliability } from '$lib/api';
  import { optionsStore } from '$lib/stores.svelte';
  import { num, pct } from '$lib/format';
  import BarChart from '$lib/components/BarChart.svelte';
  import RouteTrack from '$lib/components/RouteTrack.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import Banner from '$lib/components/Banner.svelte';

  let { onairport }: { onairport?: (iata: string) => void } = $props();

  let origin = $state('ATL');
  let dest = $state('ORD');
  let result = $state<RouteReliability | null>(null);
  let scored = $state<{ origin: string; dest: string } | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);

  const opts = $derived(optionsStore.data);

  async function lookup() {
    if (origin === dest) {
      error = 'Origin and destination must differ — pick two airports.';
      return;
    }
    loading = true;
    error = null;
    try {
      result = await api.routeReliability(origin, dest);
      scored = { origin, dest };
    } catch (e) {
      error = e instanceof Error ? e.message : 'Could not pull this route record.';
    } finally {
      loading = false;
    }
  }

  const carrierBars = $derived(
    (result?.by_carrier ?? []).map((c) => ({ label: c.carrier, value: c.delay_rate }))
  );
</script>

<section class="wrap">
  <div class="panel">
    <p class="eyebrow">Route records · 2022–2025</p>
    <p class="lede">
      The on-time history behind any city pair, by operator. These are facts from the books —
      what actually happened — to sit beside the model's estimate of what might.
    </p>

    <form
      class="lookup"
      onsubmit={(e) => {
        e.preventDefault();
        lookup();
      }}
    >
      <div class="field">
        <label for="r-origin">From</label>
        <select id="r-origin" bind:value={origin}>
          {#each opts?.airports ?? [] as a (a.iata)}
            <option value={a.iata}>{a.iata}</option>
          {/each}
        </select>
      </div>
      <span class="dash" aria-hidden="true">→</span>
      <div class="field">
        <label for="r-dest">To</label>
        <select id="r-dest" bind:value={dest}>
          {#each opts?.airports ?? [] as a (a.iata)}
            <option value={a.iata}>{a.iata}</option>
          {/each}
        </select>
      </div>
      <button type="submit" disabled={loading}>{loading ? 'Pulling…' : 'Pull record'}</button>
    </form>

    {#if loading}
      <Spinner label="Pulling the route record…" />
    {:else if error}
      <Banner kind="error" message={error} />
    {:else if result && scored}
      <div class="track-host">
        <RouteTrack origin={scored.origin} dest={scored.dest} progress={result.delay_rate} />
      </div>

      <div class="readouts">
        <div class="ro">
          <span class="ro-k eyebrow">Delay rate</span>
          <span class="ro-v mono">{pct(result.delay_rate)}</span>
        </div>
        <div class="ro">
          <span class="ro-k eyebrow">Flights on record</span>
          <span class="ro-v mono">{num(result.flights)}</span>
        </div>
        <div class="ro">
          <span class="ro-k eyebrow">Avg delay</span>
          <span class="ro-v mono">{result.avg_delay_min}<small>min</small></span>
        </div>
      </div>

      <div class="chart-head">
        <h3>Delay rate by operator</h3>
        <span class="mono dim">{scored.origin}→{scored.dest}</span>
      </div>
      <BarChart data={carrierBars} height={150} color="#ff5ad0" ariaLabel="Delay rate by operator" />

      {#if onairport}
        <button class="bridge" onclick={() => onairport?.(scored!.origin)}>
          Open {scored.origin} on the live map →
        </button>
      {/if}
    {:else}
      <div class="empty">Pick a city pair and pull its record to see the on-time history.</div>
    {/if}
  </div>

  <aside class="panel note">
    <p class="eyebrow">Reading the record</p>
    <ul>
      <li>
        <span class="mono nav-k">DELAY</span> a departure 15+ minutes late — the BTS
        <code>DepDel15</code> flag.
      </li>
      <li>
        <span class="mono nav-k">WINDOW</span> rates span 2022–2025, the model's training era, in
        the gold marts.
      </li>
      <li>
        <span class="mono nav-k">BRIDGE</span> any airport on the live map opens its full live +
        historical profile.
      </li>
      <li>
        <span class="mono nav-k">VS&nbsp;MODEL</span> records show what happened; the flight-risk
        page estimates what might.
      </li>
    </ul>
  </aside>
</section>

<style>
  .wrap {
    display: grid;
    grid-template-columns: 1fr minmax(230px, 300px);
    gap: 1rem;
    align-items: start;
  }
  @media (max-width: 880px) {
    .wrap {
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
  .lookup {
    display: flex;
    align-items: flex-end;
    gap: 0.6rem;
    margin-bottom: 1.2rem;
    flex-wrap: wrap;
  }
  .field {
    display: flex;
    flex-direction: column;
    gap: 0.28rem;
  }
  label {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.64rem;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--faint);
  }
  select {
    background: var(--panel-2);
    border: 1px solid var(--line);
    color: var(--text);
    border-radius: var(--r);
    padding: 0.55rem 0.7rem;
    font-size: 0.9rem;
    font-family: 'IBM Plex Mono', monospace;
    min-width: 78px;
  }
  select:focus {
    outline: 2px solid var(--nav);
    border-color: var(--nav);
  }
  .dash {
    color: var(--nav);
    padding-bottom: 0.55rem;
    font-size: 1.1rem;
  }
  button[type='submit'] {
    background: var(--nav);
    color: #0a0e13;
    font-family: 'Saira Semi Condensed', sans-serif;
    font-weight: 700;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    border: none;
    border-radius: var(--r);
    padding: 0.6rem 1rem;
    font-size: 0.86rem;
    cursor: pointer;
  }
  button[type='submit']:hover:not(:disabled) {
    filter: brightness(1.12);
  }
  button[type='submit']:disabled {
    opacity: 0.55;
  }
  .track-host {
    padding: 0.3rem 0.2rem 1.2rem;
  }
  .readouts {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 0.6rem;
    margin-bottom: 1.4rem;
  }
  .ro {
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-top: 2px solid var(--nav-dim);
    border-radius: var(--r);
    padding: 0.7rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .ro-v {
    font-size: 1.7rem;
    font-weight: 600;
    line-height: 1;
  }
  .ro-v small {
    font-size: 0.7rem;
    color: var(--muted);
    margin-left: 0.25rem;
  }
  .chart-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 0.7rem;
  }
  h3 {
    font-size: 0.95rem;
    font-weight: 600;
  }
  .dim {
    color: var(--faint);
    font-size: 0.74rem;
  }
  .bridge {
    margin-top: 1.1rem;
    width: 100%;
    background: transparent;
    border: 1px solid var(--line);
    border-radius: var(--r);
    color: var(--nav);
    padding: 0.55rem;
    font-size: 0.82rem;
    cursor: pointer;
    transition:
      border-color 0.15s,
      background 0.15s;
  }
  .bridge:hover {
    border-color: var(--nav);
    background: color-mix(in srgb, var(--nav) 9%, transparent);
  }
  .empty {
    color: var(--muted);
    font-size: 0.86rem;
    padding: 1.6rem 0;
    text-align: center;
  }
  .note ul {
    margin: 0.4rem 0 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.7rem;
    font-size: 0.82rem;
    color: var(--muted);
    line-height: 1.5;
  }
  .nav-k {
    color: var(--nav);
    font-size: 0.64rem;
    letter-spacing: 0.1em;
    margin-right: 0.45rem;
  }
  .note code {
    background: var(--panel-2);
    border: 1px solid var(--line);
    padding: 0.02rem 0.3rem;
    border-radius: var(--r-sharp);
    font-size: 0.76rem;
    font-family: 'IBM Plex Mono', monospace;
  }
</style>
