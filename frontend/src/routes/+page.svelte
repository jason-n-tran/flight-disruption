<script lang="ts">
  import { onMount } from 'svelte';
  import { optionsStore, healthStore } from '$lib/stores.svelte';
  import { USE_MOCK } from '$lib/api';
  import LiveMapView from '$lib/views/LiveMapView.svelte';
  import RiskLookup from '$lib/views/RiskLookup.svelte';
  import Reliability from '$lib/views/Reliability.svelte';
  import Banner from '$lib/components/Banner.svelte';

  type Page = 'traffic' | 'risk' | 'records';
  let page = $state<Page>('risk');
  let selectedAirport = $state<string | null>(null);
  let showOfflineBanner = $state(true);

  // Soft-keys named like an MFD page bar — each is a real working surface.
  const pages: { id: Page; key: string; label: string }[] = [
    { id: 'traffic', key: 'TFC', label: 'Live traffic' },
    { id: 'risk', key: 'RSK', label: 'Flight risk' },
    { id: 'records', key: 'REC', label: 'Route records' }
  ];

  function gotoAirport(iata: string) {
    selectedAirport = iata;
    page = 'traffic';
  }

  onMount(() => {
    optionsStore.load();
    healthStore.check();
  });

  const offline = $derived(healthStore.reachable === false && !USE_MOCK);
  // Link state drives the annunciator lamp: ARMED while checking, then state.
  const link = $derived(
    USE_MOCK
      ? { cls: 'sim', text: 'SIM' }
      : healthStore.reachable === true
        ? { cls: 'ok', text: 'LINK' }
        : healthStore.reachable === false
          ? { cls: 'warn', text: 'NO LINK' }
          : { cls: 'arm', text: 'ARMED' }
  );
</script>

<div class="bezel">
  <!-- Annunciator strip: the cockpit status bar. -->
  <div class="annunciator">
    <div class="ident">
      <span class="glyph" aria-hidden="true">
        <svg viewBox="0 0 24 24" width="20" height="20">
          <path
            d="M12 2 L13.4 10 L22 13.5 L22 15 L13.4 13 L13 19 L16 21 L16 22 L12 20.7 L8 22 L8 21 L11 19 L10.6 13 L2 15 L2 13.5 L10.6 10 Z"
            fill="currentColor"
          />
        </svg>
      </span>
      <span class="callsign mono">FDX&nbsp;OPS</span>
    </div>

    <div class="lamps" aria-label="System status">
      <span class="lamp {link.cls}"><i></i>{link.text}</span>
      {#if healthStore.data}
        <span class="lamp data mono" title="gold data version">
          <i></i>DATA {healthStore.data.data_version}
        </span>
      {/if}
    </div>
  </div>

  <!-- Marquee: the page's thesis in one line. -->
  <header class="marquee">
    <div>
      <p class="eyebrow">Operations console · US national airspace</p>
      <h1>Flight Disruption Intelligence</h1>
    </div>
    <p class="sub">
      Watch live traffic, score a flight's delay risk before it pushes back, and read the
      record behind any route. Risk is a probability, never a promise.
    </p>
  </header>

  {#if offline && showOfflineBanner}
    <div class="banner-slot">
      <Banner
        kind="warn"
        message="No link to the serving API. The console is fully drawn; live traffic and risk scores resume the moment the API answers. Set PUBLIC_API_BASE, or PUBLIC_USE_MOCK=true to fly the self-contained demo."
        ondismiss={() => (showOfflineBanner = false)}
      />
    </div>
  {/if}

  <!-- Page soft-keys. -->
  <div class="softkeys" role="tablist" aria-label="Console pages">
    {#each pages as p (p.id)}
      <button
        role="tab"
        aria-selected={page === p.id}
        class:active={page === p.id}
        onclick={() => (page = p.id)}
      >
        <span class="sk-key mono">{p.key}</span>
        <span class="sk-label">{p.label}</span>
      </button>
    {/each}
  </div>

  <main>
    <!-- Map stays mounted (keeps the poll loop + map state) but hidden off-page. -->
    <div class="screen" class:hidden={page !== 'traffic'} role="tabpanel" aria-label="Live traffic">
      <LiveMapView bind:selectedAirport />
    </div>
    {#if page === 'risk'}
      <div class="screen" role="tabpanel" aria-label="Flight risk">
        <RiskLookup />
      </div>
    {/if}
    {#if page === 'records'}
      <div class="screen" role="tabpanel" aria-label="Route records">
        <Reliability onairport={gotoAirport} />
      </div>
    {/if}
  </main>

  <footer>
    <span class="mono">BTS On-Time Performance · OpenSky · Open-Meteo · OpenFlights</span>
    <span class="mono">SvelteKit · MapLibre · LightGBM</span>
  </footer>
</div>

<style>
  .bezel {
    max-width: 1320px;
    margin: 0 auto;
    padding: clamp(0.6rem, 2vw, 1.4rem);
    display: flex;
    flex-direction: column;
    gap: 0.9rem;
  }

  /* ---- annunciator strip ---- */
  .annunciator {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    background: var(--bezel);
    border: 1px solid var(--line);
    border-radius: var(--r);
    padding: 0.4rem 0.7rem;
  }
  .ident {
    display: flex;
    align-items: center;
    gap: 0.55rem;
  }
  .glyph {
    color: var(--nav);
    line-height: 0;
    filter: drop-shadow(0 0 6px rgba(255, 90, 208, 0.5));
  }
  .callsign {
    font-size: 0.8rem;
    font-weight: 600;
    letter-spacing: 0.18em;
    color: var(--text);
  }
  .lamps {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    flex-wrap: wrap;
    justify-content: flex-end;
  }
  .lamp {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.66rem;
    font-weight: 600;
    letter-spacing: 0.12em;
    color: var(--muted);
    border: 1px solid var(--line);
    border-radius: var(--r-sharp);
    padding: 0.2rem 0.5rem;
    background: #0c1118;
  }
  .lamp i {
    width: 7px;
    height: 7px;
    border-radius: 50%;
    background: var(--faint);
    flex: none;
  }
  .lamp.ok {
    color: var(--ok);
    border-color: color-mix(in srgb, var(--ok) 40%, var(--line));
  }
  .lamp.ok i {
    background: var(--ok);
    box-shadow: 0 0 7px var(--ok);
    animation: blink 2.4s ease-in-out infinite;
  }
  .lamp.warn {
    color: var(--warn);
    border-color: color-mix(in srgb, var(--warn) 45%, var(--line));
  }
  .lamp.warn i {
    background: var(--warn);
    box-shadow: 0 0 7px var(--warn);
  }
  .lamp.sim {
    color: var(--info);
    border-color: color-mix(in srgb, var(--info) 40%, var(--line));
  }
  .lamp.sim i {
    background: var(--info);
    box-shadow: 0 0 7px var(--info);
  }
  .lamp.arm i {
    animation: blink 0.8s steps(2) infinite;
  }
  .lamp.data {
    color: var(--info);
    border-color: color-mix(in srgb, var(--info) 28%, var(--line));
  }
  .lamp.data i {
    background: var(--info);
  }
  @keyframes blink {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.35;
    }
  }

  /* ---- marquee ---- */
  .marquee {
    display: grid;
    grid-template-columns: 1.1fr 1fr;
    align-items: end;
    gap: 1.5rem;
    padding: 0.4rem 0.3rem 0.2rem;
  }
  h1 {
    font-size: clamp(1.8rem, 4.2vw, 3.1rem);
    font-weight: 800;
    line-height: 0.95;
    text-transform: uppercase;
    color: var(--text);
    margin-top: 0.25rem;
  }
  .marquee .sub {
    margin: 0;
    color: var(--muted);
    font-size: 0.9rem;
    line-height: 1.55;
    max-width: 46ch;
  }
  @media (max-width: 760px) {
    .marquee {
      grid-template-columns: 1fr;
      gap: 0.6rem;
    }
  }

  /* ---- soft-keys ---- */
  .softkeys {
    display: flex;
    gap: 0.4rem;
    border-top: 1px solid var(--line);
    border-bottom: 1px solid var(--line);
    padding: 0.4rem 0;
  }
  .softkeys button {
    display: flex;
    align-items: center;
    gap: 0.55rem;
    background: transparent;
    border: 1px solid transparent;
    border-radius: var(--r);
    color: var(--muted);
    padding: 0.5rem 0.85rem;
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s,
      background 0.15s;
  }
  .softkeys button:hover {
    color: var(--text);
    background: #0e141d;
  }
  .softkeys button.active {
    color: var(--text);
    border-color: color-mix(in srgb, var(--nav) 50%, var(--line));
    background: color-mix(in srgb, var(--nav) 9%, transparent);
  }
  .sk-key {
    font-size: 0.7rem;
    font-weight: 600;
    letter-spacing: 0.1em;
    color: var(--faint);
    border: 1px solid var(--line);
    border-radius: var(--r-sharp);
    padding: 0.1rem 0.32rem;
  }
  .softkeys button.active .sk-key {
    color: var(--nav);
    border-color: color-mix(in srgb, var(--nav) 55%, var(--line));
  }
  .sk-label {
    font-size: 0.92rem;
    font-weight: 500;
  }

  main {
    min-height: 420px;
  }
  .screen.hidden {
    display: none;
  }

  footer {
    display: flex;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.5rem;
    color: var(--faint);
    font-size: 0.66rem;
    letter-spacing: 0.08em;
    border-top: 1px solid var(--line);
    padding-top: 0.9rem;
  }
</style>
