/** App-wide reactive state (Svelte 5 runes-in-modules via .svelte.ts). */
import { api, type Health, type MetaOptions } from './api';

class OptionsStore {
  data = $state<MetaOptions | null>(null);
  error = $state<string | null>(null);
  loading = $state(false);
  private started = false;

  async load() {
    if (this.started) return;
    this.started = true;
    this.loading = true;
    try {
      this.data = await api.options();
      this.error = null;
    } catch (e) {
      this.error = e instanceof Error ? e.message : 'failed to load options';
    } finally {
      this.loading = false;
    }
  }
}

class HealthStore {
  data = $state<Health | null>(null);
  reachable = $state<boolean | null>(null);

  async check() {
    try {
      this.data = await api.health();
      this.reachable = true;
    } catch {
      this.reachable = false;
    }
  }
}

export const optionsStore = new OptionsStore();
export const healthStore = new HealthStore();
