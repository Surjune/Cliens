/**
 * Coordinate-order conversion, in exactly one place.
 *
 * GeoJSON is always `[longitude, latitude]` (RFC 7946). Leaflet is always
 * `[latitude, longitude]`. Getting this backwards is the most common geospatial
 * bug there is, and it fails quietly — a Chennai site lands in the Atlantic and
 * still produces a plausible-looking score.
 *
 * Every conversion in the app goes through this module. Components never reorder
 * a coordinate pair inline.
 */
import area from '@turf/area';
import { polygon as turfPolygon } from '@turf/helpers';

import type { PolygonGeometry } from '@/types/api';

/** Square metres in one square foot — exact, since 1 inch is 25.4 mm exactly. */
const SQ_METRES_PER_SQ_FOOT = 0.09290304;

/** A `[longitude, latitude]` pair, as GeoJSON stores it. */
export type GeoJsonPosition = [number, number];

/** Convert Leaflet `[lat, lng]` pairs to a GeoJSON ring, closing it if needed. */
export function leafletToRing(points: [number, number][]): GeoJsonPosition[] {
  const ring: GeoJsonPosition[] = points.map(([latitude, longitude]) => [longitude, latitude]);

  const first = ring[0];
  const last = ring[ring.length - 1];
  if (first !== undefined && last !== undefined && (first[0] !== last[0] || first[1] !== last[1])) {
    ring.push([first[0], first[1]]);
  }
  return ring;
}

/** Build a GeoJSON Polygon from Leaflet coordinates. */
export function polygonFromLeaflet(points: [number, number][]): PolygonGeometry {
  return { type: 'Polygon', coordinates: [leafletToRing(points)] };
}

/**
 * Area of a polygon in square feet, for immediate on-map feedback.
 *
 * This is a display convenience only. The authoritative area is computed by
 * PostGIS from the submitted geometry and returned by the API — the client's
 * figure is never sent to the server or used in a score.
 */
export function approximateAreaSqFt(geometry: PolygonGeometry): number {
  const feature = turfPolygon(geometry.coordinates);
  return area(feature) / SQ_METRES_PER_SQ_FOOT;
}

