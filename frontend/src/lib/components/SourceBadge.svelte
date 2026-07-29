<script lang="ts">
  import type { LiveSource } from '$lib/api';

  let {
    source,
    asOf,
    staleSeconds,
    count
  }: { source: LiveSource; asOf: number; staleSeconds: number; count: number } = $props();

  const labels: Record<LiveSource, string> = {
    live: 'LIVE',
    cached: 'CACHED',
    sample: 'SAMPLE'
  };
  // Codified: live = nominal, cached = caution, sample = inert.
  const colors: Record<LiveSource, string> = {
    live: 'var(--ok)',
    cached: 'var(--caution)',
    sample: 'var(--faint)'
  };
  const stale = $derived(staleSeconds > 90);
  const asOfStr = $derived(new Date(asOf * 1000).toLocaleTimeString([], { hour12: false }));
</script>

<div class="badge mono" title="feed as of {asOfStr}">
  <span class="dot" class:pulse={source === 'live'} style="background:{colors[source]}"></span>
  <span class="src" style="color:{colors[source]}">{labels[source]}</span>
  <span class="sep">·</span>
  <span class="cnt">{count.toLocaleString()} acft</span>
  <span class="sep">·</span>
  <span class:warn={stale}>
    {stale ? `+${staleSeconds}s stale` : asOfStr}
  </span>
</div>

<style>
  .badge {
    display: inline-flex;
    align-items: center;
    gap: 0.42rem;
    background: rgba(5, 7, 10, 0.85);
    border: 1px solid var(--line);
    border-radius: var(--r);
    padding: 0.34rem 0.7rem;
    font-size: 0.72rem;
    letter-spacing: 0.04em;
    color: var(--muted);
    backdrop-filter: blur(6px);
  }
  .dot {
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex: none;
  }
  .dot.pulse {
    animation: pulse 1.8s ease-in-out infinite;
  }
  @keyframes pulse {
    0%,
    100% {
      box-shadow: 0 0 0 0 color-mix(in srgb, var(--ok) 55%, transparent);
    }
    50% {
      box-shadow: 0 0 0 5px transparent;
    }
  }
  .src {
    font-weight: 600;
    letter-spacing: 0.1em;
  }
  .cnt {
    color: var(--text);
  }
  .sep {
    opacity: 0.35;
  }
  .warn {
    color: var(--caution);
  }
</style>
