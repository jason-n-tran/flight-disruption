<script lang="ts">
  let { label = 'Loading…', small = false }: { label?: string; small?: boolean } = $props();
</script>

<div class="wrap" class:small role="status" aria-live="polite">
  <span class="spin" aria-hidden="true"></span>
  <span class="lbl">{label}</span>
</div>

<style>
  .wrap {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    color: var(--muted);
    padding: 1rem;
    font-size: 0.85rem;
  }
  .wrap.small {
    padding: 0.4rem;
    font-size: 0.76rem;
  }
  .spin {
    width: 18px;
    height: 18px;
    border: 2px solid var(--line);
    border-top-color: var(--nav);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
    flex: none;
  }
  @keyframes spin {
    to {
      transform: rotate(360deg);
    }
  }
</style>
