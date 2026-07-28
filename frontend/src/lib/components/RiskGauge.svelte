<script lang="ts">
  /** The dominant readout: a banded delay-probability scale with the historical
   * base-rate tick and the model's needle, in the cockpit caution language. */
  import { RISK_COLORS, type RiskBand } from '$lib/api';

  let {
    probability,
    band,
    baseline
  }: { probability: number; band: RiskBand; baseline?: number } = $props();

  const color = $derived(RISK_COLORS[band]);
  const bandWord: Record<RiskBand, string> = {
    low: 'LOW',
    moderate: 'CAUTION',
    high: 'WARNING'
  };
</script>

<div class="gauge">
  <div class="readout">
    <span class="big mono" style="color:{color}">{(probability * 100).toFixed(0)}<small>%</small></span>
    <div class="meta">
      <span class="band mono" style="color:{color}; border-color:{color}66; background:{color}14">
        {bandWord[band]}
      </span>
      <span class="cap eyebrow">delay probability</span>
    </div>
  </div>

  <div
    class="scale"
    role="img"
    aria-label="Delay probability {(probability * 100).toFixed(0)} percent, {band} risk"
  >
    <span class="seg low"></span>
    <span class="seg mod"></span>
    <span class="seg high"></span>
    {#if baseline !== undefined}
      <span class="base" style="left:{baseline * 100}%" title="historical base rate {(baseline * 100).toFixed(0)}%"></span>
    {/if}
    <span class="needle" style="left:{probability * 100}%; background:{color}"></span>
  </div>

  <div class="ticks mono">
    <span>0</span>
    <span class="t20">20</span>
    <span class="t45">45</span>
    <span>100</span>
  </div>
  {#if baseline !== undefined}
    <p class="basenote mono">base rate {(baseline * 100).toFixed(0)}% · dashed tick</p>
  {/if}
</div>

<style>
  .gauge {
    width: 100%;
  }
  .readout {
    display: flex;
    align-items: center;
    gap: 0.9rem;
    margin-bottom: 0.7rem;
  }
  .big {
    font-size: 3.4rem;
    font-weight: 600;
    line-height: 0.85;
    letter-spacing: -0.02em;
  }
  .big small {
    font-size: 1.3rem;
    margin-left: 0.1rem;
    opacity: 0.7;
  }
  .meta {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }
  .band {
    align-self: flex-start;
    font-size: 0.72rem;
    font-weight: 600;
    letter-spacing: 0.14em;
    padding: 0.18rem 0.5rem;
    border-radius: var(--r-sharp);
    border: 1px solid;
  }
  .cap {
    color: var(--faint);
  }
  .scale {
    position: relative;
    height: 12px;
    border-radius: var(--r-sharp);
    overflow: hidden;
    display: flex;
    border: 1px solid var(--bezel);
  }
  .seg {
    height: 100%;
  }
  .seg.low {
    width: 20%;
    background: color-mix(in srgb, var(--ok) 32%, transparent);
  }
  .seg.mod {
    width: 25%;
    background: color-mix(in srgb, var(--caution) 32%, transparent);
  }
  .seg.high {
    width: 55%;
    background: color-mix(in srgb, var(--warn) 32%, transparent);
  }
  .needle {
    position: absolute;
    top: -3px;
    width: 3px;
    height: 18px;
    border-radius: 1px;
    transform: translateX(-50%);
    box-shadow:
      0 0 8px currentColor,
      0 0 0 1px var(--bezel);
  }
  .base {
    position: absolute;
    top: -2px;
    bottom: -2px;
    width: 0;
    border-left: 2px dashed var(--text);
    transform: translateX(-50%);
    opacity: 0.85;
  }
  .ticks {
    position: relative;
    height: 1rem;
    margin-top: 3px;
    font-size: 0.6rem;
    color: var(--faint);
  }
  .ticks span {
    position: absolute;
    transform: translateX(-50%);
  }
  .ticks span:first-child {
    left: 0;
    transform: none;
  }
  .ticks .t20 {
    left: 20%;
  }
  .ticks .t45 {
    left: 45%;
  }
  .ticks span:last-child {
    left: auto;
    right: 0;
    transform: none;
  }
  .basenote {
    margin: 0.5rem 0 0;
    font-size: 0.66rem;
    color: var(--faint);
    letter-spacing: 0.04em;
  }
</style>
