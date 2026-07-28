<script lang="ts">
  import { api, type AirportDetail } from '$lib/api';
  import { pct, hhmm } from '$lib/format';
  import BarChart from './BarChart.svelte';
  import Spinner from './Spinner.svelte';
  import Banner from './Banner.svelte';

  let { iata, onclose }: { iata: string; onclose: () => void } = $props();

  let detail = $state<AirportDetail | null>(null);
  let error = $state<string | null>(null);
  let loading = $state(true);

  const congestionColor: Record<string, string> = {
    low: 'var(--ok)',
    moderate: 'var(--caution)',
    high: 'var(--warn)'
  };

  $effect(() => {
    const code = iata;
    loading = true;
    error = null;
    detail = null;
    api
      .airport(code)
      .then((d) => {
        if (code === iata) detail = d;
      })
      .catch((e) => {
        if (code === iata) error = e instanceof Error ? e.message : 'Could not load this airport.';
      })
      .finally(() => {
        if (code === iata) loading = false;
      });
  });

  const hourBars = $derived(
    (detail?.historical.by_hour ?? []).map((h) => ({
      label: hhmm(h.hour).slice(0, 2),
      value: h.delay_rate
    }))
  );
</script>

<aside class="panel" aria-label="Airport detail">
  <header>
    <div>
      <p class="eyebrow">Station</p>
      <h2 class="mono">{iata}</h2>
      <p class="sub">{detail?.name ?? '—'}</p>
    </div>
    <button class="close" onclick={onclose} aria-label="Close panel">×</button>
  </header>

  {#if loading}
    <Spinner label="Loading {iata}…" />
  {:else if error}
    <Banner kind="error" message={error} />
  {:else if detail}
    <!-- The fusion: historical record beside the live picture. -->
    <div class="fusion">
      <div class="cell">
        <span class="k eyebrow">On-time record</span>
        <span class="v mono">{pct(detail.historical.overall_delay_rate)}</span>
        <span class="tag hist mono">HIST · delay rate</span>
      </div>
      <div class="cell">
        <span class="k eyebrow">Overhead now</span>
        <span class="v mono" style="color:{congestionColor[detail.live_congestion.level]}">
          {detail.live_congestion.aircraft_nearby}
        </span>
        <span
          class="tag live mono"
          style="color:{congestionColor[detail.live_congestion.level]}; border-color:{congestionColor[detail.live_congestion.level]}55"
        >
          LIVE · {detail.live_congestion.level}
        </span>
      </div>
    </div>

    <section>
      <div class="sec-head">
        <h3>Delay rate by hour</h3>
        <span class="hint mono">dep hour (local)</span>
      </div>
      <BarChart data={hourBars} height={120} color="#ff5ad0" ariaLabel="Delay rate by hour for {iata}" />
    </section>

    <section>
      <h3>Toughest departures from {iata}</h3>
      <ul class="routes">
        {#each detail.historical.worst_routes as r (r.dest)}
          <li>
            <span class="dest mono">{iata}→{r.dest}</span>
            <span class="rbar"><span style="width:{Math.min(100, r.delay_rate * 100)}%"></span></span>
            <span class="rate mono">{pct(r.delay_rate)}</span>
          </li>
        {/each}
      </ul>
    </section>

    <p class="foot">Overhead-now fuses the live OpenSky feed with the on-time record from the books.</p>
  {/if}
</aside>

<style>
  .panel {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    height: 100%;
    overflow-y: auto;
    padding: 1.1rem;
  }
  header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }
  h2 {
    margin: 0.1rem 0 0;
    font-size: 1.9rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: var(--text);
  }
  .sub {
    margin: 0.15rem 0 0;
    color: var(--muted);
    font-size: 0.8rem;
  }
  .close {
    background: transparent;
    border: 1px solid var(--line);
    color: var(--muted);
    width: 30px;
    height: 30px;
    border-radius: var(--r);
    font-size: 1.2rem;
    cursor: pointer;
    line-height: 1;
    flex: none;
  }
  .close:hover {
    color: var(--text);
    border-color: var(--nav);
  }
  .fusion {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.6rem;
  }
  .cell {
    background: var(--panel-2);
    border: 1px solid var(--line);
    border-radius: var(--r);
    padding: 0.7rem 0.75rem;
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }
  .v {
    font-size: 1.7rem;
    font-weight: 600;
    line-height: 1;
  }
  .tag {
    align-self: flex-start;
    margin-top: 0.2rem;
    font-size: 0.6rem;
    letter-spacing: 0.08em;
    padding: 0.12rem 0.4rem;
    border-radius: var(--r-sharp);
    border: 1px solid var(--line);
  }
  .tag.hist {
    color: var(--info);
    border-color: color-mix(in srgb, var(--info) 35%, var(--line));
  }
  .sec-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    margin-bottom: 0.6rem;
  }
  section h3 {
    font-size: 0.9rem;
    font-weight: 600;
  }
  .hint {
    font-size: 0.62rem;
    color: var(--faint);
  }
  section:has(h3:only-child) h3 {
    margin-bottom: 0.6rem;
  }
  .routes {
    list-style: none;
    margin: 0.6rem 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
  }
  .routes li {
    display: grid;
    grid-template-columns: 82px 1fr 44px;
    align-items: center;
    gap: 0.55rem;
    font-size: 0.78rem;
  }
  .rbar {
    height: 7px;
    background: var(--bezel);
    border: 1px solid var(--line-soft);
    border-radius: var(--r-sharp);
    overflow: hidden;
  }
  .rbar span {
    display: block;
    height: 100%;
    background: linear-gradient(90deg, var(--caution), var(--warn));
  }
  .rate {
    text-align: right;
    color: var(--muted);
  }
  .foot {
    margin: 0;
    font-size: 0.7rem;
    color: var(--faint);
    border-top: 1px solid var(--line);
    padding-top: 0.7rem;
    line-height: 1.5;
  }
</style>
