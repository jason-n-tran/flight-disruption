<script lang="ts">
  /**
   * The signature element: a navigation "route track" rendered the way an
   * avionics MFD draws a course — origin fix, the magenta course line, an
   * aircraft glyph at `progress`, and the destination fix. Reused wherever a
   * route is shown (risk result, route records, airport panel header).
   */
  let {
    origin,
    dest,
    progress = 0.5,
    label = ''
  }: { origin: string; dest: string; progress?: number; label?: string } = $props();

  const clamped = $derived(Math.max(0.04, Math.min(0.96, progress)));
</script>

<div class="track" role="img" aria-label="Route {origin} to {dest}">
  <span class="fix origin mono">{origin}</span>
  <span class="line">
    <span class="rail"></span>
    <span class="course" style="width:{clamped * 100}%"></span>
    <span class="dep"></span>
    <span class="ac" style="left:{clamped * 100}%" aria-hidden="true">
      <svg viewBox="0 0 24 24" width="15" height="15">
        <path
          d="M12 2 L13.4 10 L22 13.5 L22 15 L13.4 13 L13 19 L16 21 L16 22 L12 20.7 L8 22 L8 21 L11 19 L10.6 13 L2 15 L2 13.5 L10.6 10 Z"
          fill="currentColor"
        />
      </svg>
    </span>
    <span class="arr"></span>
    {#if label}<span class="caption mono">{label}</span>{/if}
  </span>
  <span class="fix dest mono">{dest}</span>
</div>

<style>
  .track {
    display: flex;
    align-items: center;
    gap: 0.7rem;
    width: 100%;
  }
  .fix {
    font-size: 0.95rem;
    font-weight: 600;
    letter-spacing: 0.06em;
    color: var(--text);
    flex: none;
  }
  .line {
    position: relative;
    flex: 1 1 auto;
    height: 26px;
    display: flex;
    align-items: center;
    min-width: 60px;
  }
  .rail {
    position: absolute;
    left: 0;
    right: 0;
    height: 0;
    border-top: 1px dashed var(--line);
  }
  .course {
    position: absolute;
    left: 0;
    height: 2px;
    background: var(--nav);
    box-shadow: 0 0 8px rgba(255, 90, 208, 0.5);
  }
  .dep,
  .arr {
    position: absolute;
    width: 7px;
    height: 7px;
    border-radius: 50%;
    top: 50%;
    transform: translateY(-50%);
  }
  .dep {
    left: 0;
    background: var(--nav);
  }
  .arr {
    right: 0;
    transform: translateY(-50%);
    background: transparent;
    border: 1.5px solid var(--muted);
  }
  .ac {
    position: absolute;
    top: 50%;
    transform: translate(-50%, -50%) rotate(90deg);
    color: var(--nav);
    line-height: 0;
    filter: drop-shadow(0 0 4px rgba(255, 90, 208, 0.6));
  }
  .caption {
    position: absolute;
    top: calc(100% - 2px);
    left: 50%;
    transform: translateX(-50%);
    font-size: 0.6rem;
    letter-spacing: 0.16em;
    color: var(--faint);
    white-space: nowrap;
  }
</style>
