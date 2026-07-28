<script lang="ts">
  /** Signed SHAP bars in the caution language: amber/red raises risk (right of
   * centre), green lowers it (left). Magnitude is the live model contribution. */
  import type { TopFactor } from '$lib/api';
  import { featureLabel } from '$lib/format';

  let { factors = [] }: { factors: TopFactor[] } = $props();

  const max = $derived(Math.max(0.0001, ...factors.map((f) => Math.abs(f.contribution))));
</script>

<ul class="factors" aria-label="Conditions driving the score">
  {#each factors as f (f.feature)}
    {@const w = (Math.abs(f.contribution) / max) * 50}
    {@const inc = f.direction === 'increases'}
    <li>
      <span class="name" title={f.feature}>{featureLabel(f.feature)}</span>
      <div
        class="track"
        role="img"
        aria-label="{featureLabel(f.feature)} {inc ? 'raises' : 'lowers'} risk by {Math.abs(f.contribution).toFixed(2)}"
      >
        <span class="mid"></span>
        {#if inc}
          <span class="fill pos" style="width:{w}%; left:50%"></span>
        {:else}
          <span class="fill neg" style="width:{w}%; right:50%"></span>
        {/if}
      </div>
      <span class="val mono" class:up={inc} class:down={!inc}>
        {inc ? '+' : '−'}{Math.abs(f.contribution).toFixed(2)}
      </span>
    </li>
  {/each}
</ul>

<style>
  .factors {
    list-style: none;
    margin: 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }
  li {
    display: grid;
    grid-template-columns: minmax(120px, 1.3fr) 2fr 54px;
    align-items: center;
    gap: 0.6rem;
  }
  .name {
    font-size: 0.8rem;
    color: var(--text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }
  .track {
    position: relative;
    height: 13px;
    background: var(--bezel);
    border: 1px solid var(--line-soft);
    border-radius: var(--r-sharp);
  }
  .mid {
    position: absolute;
    left: 50%;
    top: -1px;
    bottom: -1px;
    width: 1px;
    background: var(--line);
  }
  .fill {
    position: absolute;
    top: 1px;
    bottom: 1px;
    border-radius: 1px;
  }
  .fill.pos {
    background: linear-gradient(90deg, color-mix(in srgb, var(--warn) 55%, transparent), var(--warn));
  }
  .fill.neg {
    background: linear-gradient(270deg, color-mix(in srgb, var(--ok) 55%, transparent), var(--ok));
  }
  .val {
    font-size: 0.76rem;
    text-align: right;
  }
  .val.up {
    color: var(--warn);
  }
  .val.down {
    color: var(--ok);
  }
  @media (max-width: 520px) {
    li {
      grid-template-columns: 1fr 1.4fr 46px;
    }
  }
</style>
