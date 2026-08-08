/**
 * Flat satellite map for close-in work.
 *
 * WHY THIS EXISTS ALONGSIDE THE GLOBE
 * A globe is the right way to *find* a place and the wrong way to *inspect* one.
 * Its camera orbits a sphere, so at building scale the ground shears under the
 * cursor and the near clipping plane starts eating the mesh. A slippy map has none
 * of those problems: it is the projection tile pyramids were designed for, so it
 * zooms to the deepest published level cleanly and a dragged rectangle lands
 * exactly where the pointer went.
 *
 * So the globe owns exploration and this owns detail. The handover is automatic —
 * see `LocationPage` — and both feed the same boundary handler, so the step after
 * cannot tell which one drew the box.
 *
 * TILES COME STRAIGHT FROM THE PROVIDER, NOT THROUGH OUR API
 * The globe has to use our compositing endpoint because it paints a single image
 * layer, so the imagery and its labels must be flattened into one picture first.
 * Leaflet stacks layers natively, so that flattening is not just unnecessary here
 * — it is actively harmful. Routing through the server turned every tile into two
 * upstream fetches plus a decode, paste and re-encode, and a single screen is
 * twenty to forty tiles. That is what made panning stutter.
 *
 * Fetching direct restores the browser's own parallelism, its HTTP cache, and
 * Leaflet's prefetching, none of which the proxy could offer.
 *
 * Leaflet is driven directly rather than through react-leaflet's components. The
 * rectangle interaction needs raw map events and temporary control of dragging,
 * which is more awkward to express through the declarative wrapper than through
 * the imperative API it wraps.
 */
import L from 'leaflet';
import 'leaflet/dist/leaflet.css';
import { useEffect, useRef, useState } from 'react';

import type { DrawnArea } from '@/components/globe/DistrictGlobe';

/** Below this the globe is the better view; at or above it, this one is. */
export const MAP_HANDOVER_ZOOM = 12;

/**
 * How far past the deepest published tile the user may keep zooming.
 *
 * Leaflet upscales the last real tile rather than requesting one that does not
 * exist, so these levels are soft rather than sharp — but a soft image that keeps
 * responding beats a zoom control that stops dead.
 */
const OVERZOOM_LEVELS = 3;

/** Deepest level the label overlay publishes; past this it returns empty tiles. */
const LABEL_MAX_ZOOM = 18;

const ESRI_BASE = 'https://server.arcgisonline.com/ArcGIS/rest/services';
const ESRI_WORLD_IMAGERY = `${ESRI_BASE}/World_Imagery/MapServer/tile/{z}/{y}/{x}`;
const ESRI_LABELS = `${ESRI_BASE}/Reference/World_Boundaries_and_Places/MapServer/tile/{z}/{y}/{x}`;
const ESRI_CLARITY =
  'https://clarity.maptiles.arcgis.com/arcgis/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}';

export function SiteMap({
  centre,
  zoom,
  area,
  drawing,
  onDraw,
  onZoomOut,
  maxZoom,
  attribution,
  zoomCommand,
  visible,
}: {
  centre: { latitude: number; longitude: number };
  zoom: number;
  area: DrawnArea | null;
  drawing: boolean;
  onDraw: (area: DrawnArea) => void;
  /** Fired when the user zooms back out far enough to want the globe again. */
  onZoomOut: (centre: { latitude: number; longitude: number }) => void;
  maxZoom: number;
  attribution: string;
  /** Bumped by the zoom buttons; the sign says which way. */
  zoomCommand: { delta: number; nonce: number } | null;
  /**
   * Whether the map is the view on screen.
   *
   * It stays mounted while hidden so switching back is instant, but Leaflet
   * measures its container on creation and a hidden container measures zero — so
   * it has to be told to re-measure whenever it becomes visible again.
   */
  visible: boolean;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const rectRef = useRef<L.Rectangle | null>(null);
  const anchorRef = useRef<L.LatLng | null>(null);
  const [ready, setReady] = useState(false);

  // Created once. Centre and zoom changes are applied through the effects below
  // rather than by rebuilding, because tearing down a Leaflet map discards its
  // tile cache and makes every prop change flash white.
  useEffect(() => {
    const element = containerRef.current;
    if (element === null || mapRef.current !== null) {
      return;
    }

    const map = L.map(element, {
      center: [centre.latitude, centre.longitude],
      zoom,
      // The page supplies its own zoom buttons, which also drive the globe. Two
      // sets of controls doing the same job in different places is worse than one.
      zoomControl: false,
      attributionControl: true,
      maxZoom: maxZoom + OVERZOOM_LEVELS,
      // Continuous rather than stepped zoom, so the wheel feels like the globe's
      // rather than jumping a whole power of two per notch.
      zoomSnap: 0,
      zoomDelta: 0.4,
      // Leaflet's default is a hard 1:1 wheel step, which feels stepped after the
      // globe's continuous zoom. Scroll-wheel smoothing makes the handover between
      // the two views far less jarring.
      scrollWheelZoom: true,
      wheelDebounceTime: 20,
      wheelPxPerZoomLevel: 100,
    });

    // Shared by every layer. `maxNativeZoom` is the deepest level actually
    // published; `maxZoom` is how far the user may keep going, with Leaflet
    // upscaling the last real tile. Letting them overshoot by OVERZOOM_LEVELS
    // means zoom never hits a wall — it goes soft, which beats stopping dead.
    const tileOptions: L.TileLayerOptions = {
      maxZoom: maxZoom + OVERZOOM_LEVELS,
      maxNativeZoom: maxZoom,
      // Keep a ring of tiles beyond the viewport so a pan reveals imagery that is
      // already loaded rather than grey.
      keepBuffer: 4,
      // Load during a pan rather than waiting for it to stop, which otherwise
      // reads as the map freezing while you drag.
      updateWhenIdle: false,
      // The opposite during a zoom: requesting a whole tile set at every
      // intermediate level throws away most of what it fetches. Updating once the
      // animation settles keeps the zoom smooth and the network quiet.
      updateWhenZooming: false,
      crossOrigin: true,
    };

    // Bottom: the layer with complete global coverage. It is the safety net that
    // shows through wherever a sharper layer above has no tile, which is why a
    // Clarity gap never appears as a hole.
    L.tileLayer(ESRI_WORLD_IMAGERY, { ...tileOptions, attribution }).addTo(map);

    // Middle: Esri's higher-resolution pool. Measured at roughly twice the edge
    // detail of the base layer at zoom 17-18. Coverage is patchy by design, hence
    // the layer beneath.
    L.tileLayer(ESRI_CLARITY, tileOptions).addTo(map);

    // Top: roads, boundaries and place names, already transparent.
    L.tileLayer(ESRI_LABELS, { ...tileOptions, maxNativeZoom: LABEL_MAX_ZOOM }).addTo(map);

    mapRef.current = map;
    setReady(true);

    // Leaflet caches the container size at creation. If this mounts before layout
    // has settled — which it does, being lazily loaded into a freshly sized
    // container — that cached size is zero and no tiles are ever requested, which
    // shows as an empty grey pane. Re-measuring on the next frame fixes it.
    requestAnimationFrame(() => {
      map.invalidateSize();
    });

    return () => {
      map.remove();
      mapRef.current = null;
    };
    // Deliberately mount-only: see the comment above about rebuilding.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Re-measure whenever the map comes back on screen. Same reason as at mount:
  // while hidden the container has no size, so Leaflet's cached dimensions are
  // stale the moment it is shown again.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready || !visible) {
      return;
    }
    const frame = requestAnimationFrame(() => {
      map.invalidateSize();
    });
    return () => {
      cancelAnimationFrame(frame);
    };
  }, [visible, ready]);

  // Follow the requested view without rebuilding the map.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) {
      return;
    }
    map.setView([centre.latitude, centre.longitude], zoom);
  }, [centre.latitude, centre.longitude, zoom, ready]);

  // Hand back to the globe when the user pulls far enough out that a flat
  // projection stops being the honest way to show where they are.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) {
      return;
    }
    const onZoomEnd = () => {
      if (map.getZoom() < MAP_HANDOVER_ZOOM) {
        const middle = map.getCenter();
        onZoomOut({ latitude: middle.lat, longitude: middle.lng });
      }
    };
    map.on('zoomend', onZoomEnd);
    return () => {
      map.off('zoomend', onZoomEnd);
    };
  }, [ready, onZoomOut]);

  // Apply a zoom-button press. The nonce is the dependency rather than the delta
  // so that pressing the same button twice zooms twice.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready || zoomCommand === null) {
      return;
    }
    map.setZoom(map.getZoom() + zoomCommand.delta);
  }, [zoomCommand, ready]);

  // Draw the committed boundary, replacing any previous one.
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) {
      return;
    }
    if (rectRef.current !== null) {
      rectRef.current.remove();
      rectRef.current = null;
    }
    if (area !== null) {
      rectRef.current = L.rectangle(
        [
          [area.south, area.west],
          [area.north, area.east],
        ],
        { color: '#7cc7f0', weight: 2, fillOpacity: 0.15 }
      ).addTo(map);
    }
  }, [area, ready]);

  /**
   * Rectangle drawing.
   *
   * Dragging is disabled for the duration so the same gesture cannot both pan the
   * map and draw on it. Leaflet gives latitude and longitude directly, so unlike
   * the globe there is no ray-to-sphere step that can miss.
   */
  useEffect(() => {
    const map = mapRef.current;
    if (map === null || !ready) {
      return;
    }

    if (!drawing) {
      map.dragging.enable();
      map.getContainer().style.cursor = '';
      return;
    }

    map.dragging.disable();
    map.getContainer().style.cursor = 'crosshair';

    let preview: L.Rectangle | null = null;

    const bounds = (a: L.LatLng, b: L.LatLng): L.LatLngBounds =>
      L.latLngBounds(a, b);

    const onDown = (event: L.LeafletMouseEvent) => {
      anchorRef.current = event.latlng;
      preview = L.rectangle(bounds(event.latlng, event.latlng), {
        color: '#7cc7f0',
        weight: 2,
        dashArray: '5,5',
        fillOpacity: 0.08,
      }).addTo(map);
    };

    const onMove = (event: L.LeafletMouseEvent) => {
      if (anchorRef.current === null || preview === null) {
        return;
      }
      preview.setBounds(bounds(anchorRef.current, event.latlng));
    };

    const onUp = (event: L.LeafletMouseEvent) => {
      const anchor = anchorRef.current;
      anchorRef.current = null;
      if (preview !== null) {
        preview.remove();
        preview = null;
      }
      if (anchor === null) {
        return;
      }

      const box = bounds(anchor, event.latlng);
      const south = box.getSouth();
      const north = box.getNorth();
      const west = box.getWest();
      const east = box.getEast();
      // A click rather than a drag. The API rejects a degenerate rectangle, so it
      // is discarded here instead of being sent.
      if (north > south && east > west) {
        onDraw({ south, north, west, east });
      }
    };

    map.on('mousedown', onDown);
    map.on('mousemove', onMove);
    map.on('mouseup', onUp);
    return () => {
      map.off('mousedown', onDown);
      map.off('mousemove', onMove);
      map.off('mouseup', onUp);
      preview?.remove();
      map.dragging.enable();
      map.getContainer().style.cursor = '';
    };
  }, [drawing, ready, onDraw]);

  // `bg-void` rather than Leaflet's default light grey: an unloaded tile should
  // read as part of this interface, not as a broken page.
  return <div ref={containerRef} className="h-full w-full bg-void" />;
}
