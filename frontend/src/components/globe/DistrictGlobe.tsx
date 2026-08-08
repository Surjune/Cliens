/**
 * 3D satellite globe. Drag the earth, shift-drag to draw a site boundary.
 *
 * IMAGERY
 * A tile engine rather than a single texture. One equirectangular JPEG is 2048 px
 * wide for the whole planet — about 20 km per pixel, so a district is a smudge.
 * `globeTileEngineUrl` streams standard slippy-map tiles instead, so resolution
 * increases as the camera descends and the imagery stays sharp all the way down to
 * building scale, over the whole globe.
 *
 * ZOOM
 * Unrestricted, from the full disc to close-in. An earlier version floored the zoom
 * at the climate grid resolution to stop the imagery implying per-building
 * precision. That guard now lives where it belongs — on the result, which states
 * how many measured cells stand behind the number and whether any of it was
 * interpolated — rather than by crippling navigation.
 *
 * SELECTION
 * Drawing is opt-in, armed by the pencil button on the page. While it is off every
 * drag rotates the earth; while it is on every drag pulls out a rectangle. There is
 * no modifier-key overlap between the two, so a drag can never do the thing the
 * user did not mean.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import Globe, { type GlobeMethods } from 'react-globe.gl';

/** Earth radius in the units react-globe.gl uses for camera altitude. */
const GLOBE_RADIUS_UNITS = 100;

const HOME_VIEW = { lat: 10.9, lng: 78.2, altitude: 1.6 };
const INITIAL_VIEW = { lat: 14, lng: 40, altitude: 3.2 };

/**
 * Closest the camera may come to the surface, as a multiple of Earth's radius.
 *
 * 0.00005 x 6371 km is about 320 m up — low enough to read a street layout and
 * pick out individual roofs. The previous value of 0.0015 worked out at 9.5 km,
 * which is why zooming appeared to stop early and then just magnified blur: the
 * camera physically could not get closer, so no deeper tiles were ever requested.
 */
const MIN_ALTITUDE = 0.00005;
const MAX_ALTITUDE = 4.5;

/**
 * Deepest tile level the engine may request, when the server has not said.
 *
 * three-globe defaults this to 17 and never asks for anything sharper, so past
 * that point zooming stretched level-17 tiles instead of loading deeper ones —
 * the "pixels breaking" effect. The real ceiling comes from the API, because it
 * depends on which imagery providers are configured; this is only the value used
 * before that answer arrives.
 *
 * It is passed as a spread prop because react-globe.gl's bundled type
 * declarations lag its runtime and omit this one. Spreading is not a workaround
 * for a missing feature: react-kapsule applies every prop it receives to the
 * underlying instance, while the component ref only exposes explicitly declared
 * methods — so a prop is the supported route and a ref call would silently do
 * nothing.
 */
const FALLBACK_TILE_LEVEL = 19;

/**
 * Tiles come from our own API, not straight from the imagery provider.
 *
 * The globe paints one image layer, but satellite imagery and its place names are
 * published as two. The backend fetches both and flattens them into a single JPEG,
 * so what arrives here already has roads, boundaries and place names on it — which
 * is what makes it possible to find an actual plot rather than an anonymous field.
 *
 * The tradeoff, stated rather than buried: this needs the network, and the imagery
 * is Esri's, whose terms require the attribution rendered in the corner. Nothing
 * about the score depends on it — the climate data is bundled locally — so if tiles
 * fail the globe still works as a picker; it just looks plain.
 */
const TILE_URL = (x: number, y: number, level: number): string =>
  `/api/tiles/${String(level)}/${String(x)}/${String(y)}`;

export interface DrawnArea {
  south: number;
  north: number;
  west: number;
  east: number;
}

function prefersReducedMotion(): boolean {
  return (
    typeof window !== 'undefined' &&
    window.matchMedia('(prefers-reduced-motion: reduce)').matches
  );
}

/** A drawn rectangle as a closed GeoJSON ring, in (lon, lat) order. */
function ringFor(area: DrawnArea): number[][] {
  return [
    [area.west, area.south],
    [area.east, area.south],
    [area.east, area.north],
    [area.west, area.north],
    [area.west, area.south],
  ];
}

/** Where the camera should be looking. Changing this flies the globe there. */
export interface CameraTarget {
  latitude: number;
  longitude: number;
  /** Camera height as a multiple of Earth's radius. */
  altitude: number;
  /** Bumped to re-trigger a flight to the same place. */
  nonce: number;
}

export function DistrictGlobe({
  area,
  drawing,
  onDraw,
  target,
  maxZoom,
  attribution,
  onDescendBelow,
  handoverAltitude,
  fullScreen = false,
}: {
  /** The committed site boundary, if one has been drawn. */
  area: DrawnArea | null;
  /** Whether drag-to-draw is armed. When false, dragging always rotates. */
  drawing: boolean;
  onDraw: (area: DrawnArea) => void;
  /** Set by a place search. Null leaves the camera where the user put it. */
  target: CameraTarget | null;
  /** Deepest zoom the server's imagery actually reaches. */
  maxZoom?: number | undefined;
  /** Credit line for whichever providers are active. */
  attribution?: string | undefined;
  /**
   * Fired once the camera drops below `handoverAltitude`.
   *
   * The globe does not switch views itself — it reports the descent and lets the
   * page decide, so the two views stay independent of each other.
   */
  onDescendBelow?: ((latitude: number, longitude: number, altitude: number) => void) | undefined;
  handoverAltitude?: number | undefined;
  fullScreen?: boolean;
}) {
  const globeRef = useRef<GlobeMethods | undefined>(undefined);
  const containerRef = useRef<HTMLDivElement>(null);
  const [ready, setReady] = useState(false);
  const [size, setSize] = useState({ width: 0, height: 0 });
  /** The rectangle currently being dragged out, shown live. */
  const [preview, setPreview] = useState<DrawnArea | null>(null);
  const anchorRef = useRef<{ lat: number; lng: number } | null>(null);

  // The WebGL canvas needs explicit pixel dimensions — it cannot be sized in
  // percentages — so the container is measured and the canvas follows it. This
  // also covers window resize and device rotation for free.
  useEffect(() => {
    const element = containerRef.current;
    if (element === null) {
      return;
    }
    const observer = new ResizeObserver(([entry]) => {
      if (entry !== undefined) {
        setSize({ width: entry.contentRect.width, height: entry.contentRect.height });
      }
    });
    observer.observe(element);
    return () => {
      observer.disconnect();
    };
  }, []);

  const handleReady = useCallback(() => {
    const globe = globeRef.current;
    if (globe === undefined) {
      return;
    }

    const controls = globe.controls();
    controls.enableDamping = true; // inertia, so drags coast rather than stop dead
    controls.dampingFactor = 0.08;
    controls.rotateSpeed = 0.4;
    // Zoom speed is constant in OrbitControls, which makes the last few metres
    // crawl and the first few thousand kilometres lurch. Damping plus a moderate
    // rate is the closest this control model gets to a proportional zoom.
    controls.zoomSpeed = 1.1;
    controls.minDistance = GLOBE_RADIUS_UNITS * (1 + MIN_ALTITUDE);
    controls.maxDistance = GLOBE_RADIUS_UNITS * (1 + MAX_ALTITUDE);

    if (!prefersReducedMotion()) {
      controls.autoRotate = true;
      controls.autoRotateSpeed = 0.28;
      controls.addEventListener('start', () => {
        controls.autoRotate = false;
      });
    }

    globe.pointOfView(INITIAL_VIEW, 0);
    globe.pointOfView(HOME_VIEW, prefersReducedMotion() ? 0 : 3000);
    setReady(true);
  }, []);

  // Report a descent past the handover point. `onZoom` fires continuously during
  // a zoom, so the guard is on altitude alone — the page unmounts this component
  // in response, which is what stops it firing repeatedly.
  const handleZoom = useCallback(
    (pov: { lat: number; lng: number; altitude: number }) => {
      if (
        onDescendBelow !== undefined &&
        handoverAltitude !== undefined &&
        pov.altitude < handoverAltitude
      ) {
        onDescendBelow(pov.lat, pov.lng, pov.altitude);
      }
    },
    [onDescendBelow, handoverAltitude]
  );

  // A search result moves the camera. `nonce` is in the dependency list so
  // searching the same place twice flies there twice, rather than being skipped
  // because the coordinates did not change.
  useEffect(() => {
    if (target === null || !ready) {
      return;
    }
    globeRef.current?.pointOfView(
      { lat: target.latitude, lng: target.longitude, altitude: target.altitude },
      prefersReducedMotion() ? 0 : 1800
    );
  }, [target, ready]);

  /**
   * Rectangle drawing, driven from raw pointer events on the canvas.
   *
   * `toGlobeCoords` converts a screen position to a point on the sphere, returning
   * null where the ray misses the globe — dragging off the edge of the earth must
   * leave the rectangle at its last valid corner rather than jumping.
   *
   * OrbitControls is disabled for the duration of a draw. Without that, the same
   * drag would rotate the planet underneath the rectangle being drawn on it.
   */
  useEffect(() => {
    const element = containerRef.current;
    const globe = globeRef.current;
    if (element === null || globe === undefined || !ready) {
      return;
    }

    const toCoords = (event: PointerEvent): { lat: number; lng: number } | null => {
      const rect = element.getBoundingClientRect();
      return globe.toGlobeCoords(event.clientX - rect.left, event.clientY - rect.top);
    };

    const onPointerDown = (event: PointerEvent) => {
      // Drawing is opt-in. With the tool off, every drag rotates the globe — no
      // modifier key, so a drag can never surprise the user by cutting a box.
      if (!drawing) {
        return;
      }
      const start = toCoords(event);
      if (start === null) {
        return;
      }
      anchorRef.current = start;
      globe.controls().enabled = false;
      element.setPointerCapture(event.pointerId);
    };

    const onPointerMove = (event: PointerEvent) => {
      const anchor = anchorRef.current;
      if (anchor === null) {
        return;
      }
      const current = toCoords(event);
      if (current === null) {
        return;
      }
      setPreview({
        south: Math.min(anchor.lat, current.lat),
        north: Math.max(anchor.lat, current.lat),
        west: Math.min(anchor.lng, current.lng),
        east: Math.max(anchor.lng, current.lng),
      });
    };

    const onPointerUp = (event: PointerEvent) => {
      if (anchorRef.current === null) {
        return;
      }
      anchorRef.current = null;
      globe.controls().enabled = true;
      if (element.hasPointerCapture(event.pointerId)) {
        element.releasePointerCapture(event.pointerId);
      }

      setPreview((current) => {
        // A click, not a drag. Degenerate rectangles are rejected by the API's
        // ordering validator anyway, so they are discarded here rather than sent.
        if (current !== null && current.north > current.south && current.east > current.west) {
          onDraw(current);
        }
        return null;
      });
    };

    element.addEventListener('pointerdown', onPointerDown);
    element.addEventListener('pointermove', onPointerMove);
    element.addEventListener('pointerup', onPointerUp);
    element.addEventListener('pointercancel', onPointerUp);
    return () => {
      element.removeEventListener('pointerdown', onPointerDown);
      element.removeEventListener('pointermove', onPointerMove);
      element.removeEventListener('pointerup', onPointerUp);
      element.removeEventListener('pointercancel', onPointerUp);
    };
  }, [ready, drawing, onDraw]);

  /** The live preview wins over the committed area while a drag is in progress. */
  const shown = preview ?? area;

  const polygons = useMemo(
    () =>
      shown === null
        ? []
        : [
            {
              geometry: { type: 'Polygon' as const, coordinates: [ringFor(shown)] },
              committed: preview === null,
            },
          ],
    [shown, preview]
  );

  return (
    <div
      ref={containerRef}
      className={`relative bg-void ${fullScreen ? 'h-full w-full' : 'h-[320px] w-full overflow-hidden rounded-xl border border-white/10'} ${
        drawing ? 'cursor-crosshair' : 'cursor-grab active:cursor-grabbing'
      }`}
      // The browser's own drag-to-pan would fight the rectangle drag on touch.
      style={{ touchAction: 'none' }}
    >
      {size.width > 0 && size.height > 0 && (
        <Globe
          ref={globeRef}
          width={size.width}
          height={size.height}
          globeTileEngineUrl={TILE_URL}
          // More segments across the sphere. At the default the horizon visibly
          // facets once the camera is low, because a coarse mesh cannot follow the
          // curvature at that scale.
          globeCurvatureResolution={1}
          {...({ globeTileEngineMaxLevel: maxZoom ?? FALLBACK_TILE_LEVEL } as Record<string, unknown>)}
          backgroundColor="rgba(0,0,0,0)"
          atmosphereColor="#7cc7f0"
          atmosphereAltitude={0.14}
          onGlobeReady={handleReady}
          onZoom={handleZoom}
          polygonsData={polygons}
          polygonGeoJsonGeometry="geometry"
          // The preview is fainter than the committed selection, so the moment the
          // drag is released reads as the boundary being accepted.
          polygonCapColor={(d) =>
            (d as { committed: boolean }).committed
              ? 'rgba(124, 199, 240, 0.20)'
              : 'rgba(124, 199, 240, 0.10)'
          }
          polygonSideColor={() => 'rgba(124, 199, 240, 0.22)'}
          polygonStrokeColor={() => '#7cc7f0'}
          polygonAltitude={0.004}
          polygonsTransitionDuration={0}
        />
      )}

      {/* Covers the canvas until the scene is genuinely up, rather than showing a
          spinner over a half-drawn globe. */}
      {!ready && (
        <div
          role="status"
          className="absolute inset-0 flex flex-col items-center justify-center gap-4 bg-void"
        >
          <div className="h-24 w-24 animate-pulse rounded-full bg-gradient-to-br from-atmos/30 to-transparent" />
          <p className="text-sm text-ink-3">Loading satellite imagery…</p>
        </div>
      )}

      {/* Attribution is a condition of using the tile service, so it is part of the
          component rather than something a page can forget. */}
      <p className="pointer-events-none absolute bottom-3 right-4 text-[10px] text-ink-3/60">
        {attribution ?? 'Imagery © Esri, Maxar, Earthstar Geographics'}
      </p>
    </div>
  );
}
