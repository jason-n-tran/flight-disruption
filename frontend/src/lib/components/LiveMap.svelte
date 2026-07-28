<script lang="ts">
  import { onDestroy, onMount } from 'svelte';
  import maplibregl from 'maplibre-gl';
  import 'maplibre-gl/dist/maplibre-gl.css';
  import { api, type AirportOption, type LivePositions } from '$lib/api';

  let {
    airports = [],
    onairportclick,
    onstatus
  }: {
    airports: AirportOption[];
    onairportclick?: (iata: string) => void;
    // Push live-feed status up to the parent for the badge / banners.
    onstatus?: (s: { positions: LivePositions | null; error: string | null; loading: boolean }) => void;
  } = $props();

  let positions: LivePositions | null = null;
  let error: string | null = null;
  let loading = true;

  function emit() {
    onstatus?.({ positions, error, loading });
  }

  let mapEl: HTMLDivElement;
  let map: maplibregl.Map | null = null;
  let pollTimer: ReturnType<typeof setInterval> | null = null;
  let ready = false;

  // OSM raster style — no API token required, Cloudflare-friendly.
  const STYLE: maplibregl.StyleSpecification = {
    version: 8,
    sources: {
      osm: {
        type: 'raster',
        tiles: ['https://tile.openstreetmap.org/{z}/{x}/{y}.png'],
        tileSize: 256,
        attribution: '© OpenStreetMap contributors'
      }
    },
    layers: [{ id: 'osm', type: 'raster', source: 'osm' }]
  };

  function aircraftGeoJSON(p: LivePositions | null): GeoJSON.FeatureCollection {
    return {
      type: 'FeatureCollection',
      features: (p?.aircraft ?? [])
        .filter((a) => !a.on_ground)
        .map((a) => ({
          type: 'Feature',
          geometry: { type: 'Point', coordinates: [a.lon, a.lat] },
          properties: {
            callsign: a.callsign,
            heading: a.heading,
            altitude: Math.round(a.altitude),
            velocity: Math.round(a.velocity)
          }
        }))
    };
  }

  function airportGeoJSON(): GeoJSON.FeatureCollection {
    return {
      type: 'FeatureCollection',
      features: airports.map((ap) => ({
        type: 'Feature',
        geometry: { type: 'Point', coordinates: [ap.lon, ap.lat] },
        properties: { iata: ap.iata, name: ap.name }
      }))
    };
  }

  // A small plane PNG built at runtime so we can rotate it via symbol layer.
  function planeIcon(): { data: Uint8Array; width: number; height: number } {
    const size = 40;
    const c = document.createElement('canvas');
    c.width = c.height = size;
    const ctx = c.getContext('2d')!;
    ctx.translate(size / 2, size / 2);
    ctx.fillStyle = '#ff5ad0'; /* navigation magenta — the signature glyph */
    ctx.strokeStyle = '#05070a';
    ctx.lineWidth = 1.2;
    // Simple top-down plane pointing up (north); symbol layer rotates by heading.
    ctx.beginPath();
    ctx.moveTo(0, -14);
    ctx.lineTo(3, -2);
    ctx.lineTo(15, 5);
    ctx.lineTo(15, 8);
    ctx.lineTo(3, 5);
    ctx.lineTo(2, 12);
    ctx.lineTo(6, 15);
    ctx.lineTo(6, 17);
    ctx.lineTo(0, 15);
    ctx.lineTo(-6, 17);
    ctx.lineTo(-6, 15);
    ctx.lineTo(-2, 12);
    ctx.lineTo(-3, 5);
    ctx.lineTo(-15, 8);
    ctx.lineTo(-15, 5);
    ctx.lineTo(-3, -2);
    ctx.closePath();
    ctx.fill();
    ctx.stroke();
    const img = ctx.getImageData(0, 0, size, size);
    return { data: new Uint8Array(img.data.buffer), width: size, height: size };
  }

  async function poll() {
    try {
      const p = await api.livePositions();
      positions = p;
      error = null;
      const src = map?.getSource('aircraft') as maplibregl.GeoJSONSource | undefined;
      src?.setData(aircraftGeoJSON(p));
    } catch (e) {
      error = e instanceof Error ? e.message : 'live feed unavailable';
    } finally {
      loading = false;
      emit();
    }
  }

  function initLayers() {
    if (!map) return;
    const icon = planeIcon();
    if (!map.hasImage('plane')) {
      map.addImage('plane', icon, { pixelRatio: 2 });
    }

    map.addSource('aircraft', { type: 'geojson', data: aircraftGeoJSON(positions) });
    map.addSource('airports', { type: 'geojson', data: airportGeoJSON() });

    map.addLayer({
      id: 'airport-dots',
      type: 'circle',
      source: 'airports',
      paint: {
        'circle-radius': 5,
        'circle-color': '#4fd4ff',
        'circle-stroke-width': 1.5,
        'circle-stroke-color': '#05070a'
      }
    });
    map.addLayer({
      id: 'airport-labels',
      type: 'symbol',
      source: 'airports',
      minzoom: 4.2,
      layout: {
        'text-field': ['get', 'iata'],
        'text-size': 11,
        'text-letter-spacing': 0.08,
        'text-offset': [0, 1.1],
        'text-anchor': 'top'
      },
      paint: {
        'text-color': '#9fb0c4',
        'text-halo-color': '#05070a',
        'text-halo-width': 1.6
      }
    });

    map.addLayer({
      id: 'aircraft-symbols',
      type: 'symbol',
      source: 'aircraft',
      layout: {
        'icon-image': 'plane',
        'icon-size': 0.5,
        'icon-rotate': ['get', 'heading'],
        'icon-rotation-alignment': 'map',
        'icon-allow-overlap': true,
        'icon-ignore-placement': true
      }
    });

    const popup = new maplibregl.Popup({ closeButton: false, closeOnClick: false, offset: 12 });
    map.on('mouseenter', 'aircraft-symbols', (e) => {
      map!.getCanvas().style.cursor = 'pointer';
      const f = e.features?.[0];
      if (!f) return;
      const pr = f.properties as Record<string, unknown>;
      const coords = (f.geometry as GeoJSON.Point).coordinates as [number, number];
      popup
        .setLngLat(coords)
        .setHTML(
          `<strong>${pr.callsign}</strong><br/>alt ${pr.altitude} m · ${pr.velocity} m/s · hdg ${Math.round(Number(pr.heading))}°`
        )
        .addTo(map!);
    });
    map.on('mouseleave', 'aircraft-symbols', () => {
      map!.getCanvas().style.cursor = '';
      popup.remove();
    });

    // Airport bridge: clicking an airport opens the detail panel.
    for (const layer of ['airport-dots', 'airport-labels']) {
      map.on('click', layer, (e) => {
        const f = e.features?.[0];
        const iata = f?.properties?.iata as string | undefined;
        if (iata) onairportclick?.(iata);
      });
      map.on('mouseenter', layer, () => (map!.getCanvas().style.cursor = 'pointer'));
      map.on('mouseleave', layer, () => (map!.getCanvas().style.cursor = ''));
    }

    ready = true;
  }

  onMount(() => {
    map = new maplibregl.Map({
      container: mapEl,
      style: STYLE,
      center: [-97, 39],
      zoom: 3.6,
      minZoom: 2,
      maxZoom: 12,
      attributionControl: { compact: true }
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), 'top-left');
    map.on('load', () => {
      initLayers();
      poll();
      pollTimer = setInterval(poll, 30_000);
    });
  });

  onDestroy(() => {
    if (pollTimer) clearInterval(pollTimer);
    map?.remove();
    map = null;
  });

  // Keep airport source in sync if the list arrives after init.
  $effect(() => {
    const _ = airports;
    if (ready && map) {
      const src = map.getSource('airports') as maplibregl.GeoJSONSource | undefined;
      src?.setData(airportGeoJSON());
    }
  });
</script>

<div class="map" bind:this={mapEl}></div>

<style>
  .map {
    position: absolute;
    inset: 0;
    background: #05070a;
  }
  :global(.maplibregl-popup-content) {
    background: var(--bezel);
    color: var(--text);
    border: 1px solid var(--line);
    border-left: 2px solid var(--nav);
    border-radius: var(--r);
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.74rem;
    box-shadow: 0 8px 28px #000a;
  }
  :global(.maplibregl-popup-content strong) {
    color: var(--nav);
    letter-spacing: 0.04em;
  }
  :global(.maplibregl-popup-tip) {
    border-top-color: var(--line) !important;
    border-bottom-color: var(--line) !important;
  }
  :global(.maplibregl-ctrl-attrib) {
    font-size: 0.6rem;
  }
  /* Tone the nav control into the bezel palette. */
  :global(.maplibregl-ctrl-group) {
    background: var(--bezel);
    border: 1px solid var(--line);
  }
  :global(.maplibregl-ctrl-group button + button) {
    border-top-color: var(--line);
  }
</style>
