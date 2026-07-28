<script lang="ts">
  /**
   * Hand-rolled SVG bar chart — no chart lib, keeps the static bundle lean.
   * Renders a labelled vertical bar series (e.g. delay rate by hour).
   */
  interface Bar {
    label: string;
    value: number; // 0..1 (treated as a rate); axis scales to data max
    highlight?: boolean;
  }

  let {
    data = [],
    height = 140,
    color = '#ff5ad0',
    formatValue = (v: number) => `${(v * 100).toFixed(0)}%`,
    ariaLabel = 'bar chart'
  }: {
    data: Bar[];
    height?: number;
    color?: string;
    formatValue?: (v: number) => string;
    ariaLabel?: string;
  } = $props();

  const max = $derived(Math.max(0.0001, ...data.map((d) => d.value)));
  let hovered = $state<number | null>(null);
</script>

<div class="chart" style="height:{height}px" role="img" aria-label={ariaLabel}>
  {#each data as d, i (d.label + i)}
    <div
      class="col"
      class:hl={d.highlight}
      onmouseenter={() => (hovered = i)}
      onmouseleave={() => (hovered = null)}
      role="presentation"
    >
      {#if hovered === i}
        <div class="tip">{d.label}: {formatValue(d.value)}</div>
      {/if}
      <div
        class="bar"
        style="height:{(d.value / max) * 100}%; background:{d.highlight ? '#ffb12e' : color}"
      ></div>
      <span class="lbl mono">{d.label}</span>
    </div>
  {/each}
</div>

<style>
  .chart {
    display: flex;
    align-items: flex-end;
    gap: 2px;
    width: 100%;
  }
  .col {
    position: relative;
    flex: 1 1 0;
    display: flex;
    flex-direction: column;
    justify-content: flex-end;
    align-items: center;
    height: 100%;
    min-width: 0;
  }
  .bar {
    width: 100%;
    border-radius: 1px 1px 0 0;
    transition:
      height 0.3s ease,
      filter 0.15s;
  }
  .col:hover .bar {
    filter: brightness(1.25);
  }
  .lbl {
    margin-top: 4px;
    font-size: 0.6rem;
    color: var(--muted);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    max-width: 100%;
  }
  .tip {
    position: absolute;
    bottom: calc(100% + 4px);
    left: 50%;
    transform: translateX(-50%);
    background: var(--bezel);
    border: 1px solid var(--line);
    color: var(--text);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.66rem;
    padding: 2px 6px;
    border-radius: var(--r-sharp);
    white-space: nowrap;
    z-index: 5;
    pointer-events: none;
  }
  .col.hl .lbl {
    color: var(--caution);
  }
</style>
