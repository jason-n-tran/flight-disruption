<script lang="ts">
  let {
    kind = 'warn',
    message,
    ondismiss
  }: { kind?: 'warn' | 'error' | 'info'; message: string; ondismiss?: () => void } = $props();
</script>

<div class="banner {kind}" role="alert">
  <span class="ico mono" aria-hidden="true">{kind === 'error' ? '✕' : kind === 'warn' ? '!' : 'i'}</span>
  <span class="msg">{message}</span>
  {#if ondismiss}
    <button class="x" onclick={ondismiss} aria-label="Dismiss">×</button>
  {/if}
</div>

<style>
  .banner {
    display: flex;
    align-items: center;
    gap: 0.65rem;
    padding: 0.6rem 0.85rem;
    border-radius: var(--r);
    font-size: 0.83rem;
    line-height: 1.45;
    border: 1px solid;
    border-left-width: 3px;
  }
  .warn {
    background: color-mix(in srgb, var(--caution) 9%, transparent);
    border-color: color-mix(in srgb, var(--caution) 50%, var(--line));
    color: var(--caution);
  }
  .error {
    background: color-mix(in srgb, var(--warn) 9%, transparent);
    border-color: color-mix(in srgb, var(--warn) 50%, var(--line));
    color: var(--warn);
  }
  .info {
    background: color-mix(in srgb, var(--info) 9%, transparent);
    border-color: color-mix(in srgb, var(--info) 50%, var(--line));
    color: var(--info);
  }
  .ico {
    font-weight: 600;
    flex: none;
    width: 1.1rem;
    height: 1.1rem;
    display: grid;
    place-items: center;
    border: 1px solid currentColor;
    border-radius: 50%;
    font-size: 0.7rem;
  }
  .msg {
    flex: 1;
    color: var(--text);
  }
  .x {
    background: none;
    border: none;
    color: inherit;
    font-size: 1.2rem;
    cursor: pointer;
    line-height: 1;
    opacity: 0.7;
  }
  .x:hover {
    opacity: 1;
  }
</style>
