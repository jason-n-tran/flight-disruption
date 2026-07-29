<script lang="ts">
  import LiveMap from '$lib/components/LiveMap.svelte';
  import AirportPanel from '$lib/components/AirportPanel.svelte';
  import SourceBadge from '$lib/components/SourceBadge.svelte';
  import Banner from '$lib/components/Banner.svelte';
  import Spinner from '$lib/components/Spinner.svelte';
  import { optionsStore } from '$lib/stores.svelte';
  import type { LivePositions } from '$lib/api';

  let { selectedAirport = $bindable(null) }: { selectedAirport?: string | null } = $props();

  const opts = $derived(optionsStore.data);

  // Status pushed up from the map's poll loop.
  let positions = $state<LivePositions | null>(null);
  let mapError = $state<string | null>(null);
  let mapLoading = $state(true);
</script>

<div class="stage">
  <LiveMap
    airports={opts?.airports ?? []}
    onairportclick={(iata) => (selectedAirport = iata)}
    onstatus={(s) => {
      positions = s.positions;
      mapError = s.error;
      mapLoading = s.loading;
    }}
  />

  <div class="overlay top">
    {#if positions}
      <SourceBadge
        source={positions.source}
        asOf={positions.as_of}
        staleSeconds={positions.stale_seconds}
        count={positions.count}
      />
    {:else if mapLoading}
      <div class="pill"><Spinner label="Connecting to live feed…" small /></div>
    {/if}
  </div>

  {#if mapError}
    <div class="overlay bottom">
      <Banner kind="warn" message="Live feed degraded: {mapError}. Showing last known / sample positions." />
    </div>
  {/if}

  <div class="hint mono">◎ tap an airport for its live + historical profile</div>

  {#if selectedAirport}
    <div class="panel-host">
      <AirportPanel iata={selectedAirport} onclose={() => (selectedAirport = null)} />
    </div>
  {/if}
</div>

<style>
  .stage {
    position: relative;
    width: 100%;
    height: calc(100vh - 250px);
    min-height: 460px;
    border: 1px solid var(--line);
    border-radius: var(--r-lg);
    overflow: hidden;
  }
  .overlay {
    position: absolute;
    z-index: 10;
    left: 50%;
    transform: translateX(-50%);
    width: max-content;
    max-width: 92%;
  }
  .overlay.top {
    top: 12px;
  }
  .overlay.bottom {
    bottom: 12px;
    width: min(92%, 640px);
  }
  .pill {
    background: rgba(5, 7, 10, 0.82);
    border: 1px solid var(--line);
    border-radius: var(--r);
    backdrop-filter: blur(6px);
  }
  .hint {
    position: absolute;
    z-index: 9;
    right: 12px;
    bottom: 28px;
    font-size: 0.68rem;
    letter-spacing: 0.04em;
    color: var(--muted);
    background: rgba(5, 7, 10, 0.82);
    border: 1px solid var(--line);
    border-radius: var(--r-sharp);
    padding: 0.3rem 0.6rem;
    backdrop-filter: blur(6px);
  }
  .panel-host {
    position: absolute;
    z-index: 20;
    top: 0;
    right: 0;
    bottom: 0;
    width: min(390px, 92%);
    background: var(--panel);
    border-left: 1px solid var(--nav-dim);
    box-shadow: -14px 0 40px #000a;
    animation: slide 0.2s ease;
  }
  @keyframes slide {
    from {
      transform: translateX(100%);
    }
    to {
      transform: translateX(0);
    }
  }
  @media (max-width: 640px) {
    .hint {
      display: none;
    }
  }
</style>
