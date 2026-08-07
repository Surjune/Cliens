/**
 * Tests for coordinate-order conversion.
 *
 * This is the highest-value test file in the frontend. GeoJSON is [lon, lat] and
 * Leaflet is [lat, lng]; getting it backwards fails silently and produces a
 * plausible-looking score for the wrong place on earth.
 */
import { describe, expect, it } from 'vitest';

import { approximateAreaSqFt, leafletToRing, polygonFromLeaflet } from './geo';

/** Chennai, near the Adyar estuary. Latitude 13, longitude 80. */
const CHENNAI_LAT = 13.01;
const CHENNAI_LON = 80.27;

/** A small square, given as Leaflet [lat, lng] pairs. */
const SQUARE_LEAFLET: [number, number][] = [
  [CHENNAI_LAT, CHENNAI_LON],
  [CHENNAI_LAT, CHENNAI_LON + 0.0004],
  [CHENNAI_LAT + 0.0004, CHENNAI_LON + 0.0004],
  [CHENNAI_LAT + 0.0004, CHENNAI_LON],
];

describe('leafletToRing', () => {
  it('swaps [lat, lng] to GeoJSON [lon, lat]', () => {
    const ring = leafletToRing([[CHENNAI_LAT, CHENNAI_LON]]);

    expect(ring[0]).toEqual([CHENNAI_LON, CHENNAI_LAT]);
  });

  it('puts longitude first, not latitude', () => {
    // Explicit rather than implied: Chennai's longitude is ~80 and latitude ~13,
    // so an accidental swap is detectable by magnitude alone.
    const ring = leafletToRing(SQUARE_LEAFLET);
    const first = ring[0];

    expect(first?.[0]).toBeCloseTo(80.27, 2);
    expect(first?.[1]).toBeCloseTo(13.01, 2);
  });

  it('closes an open ring', () => {
    const ring = leafletToRing(SQUARE_LEAFLET);

    expect(ring).toHaveLength(SQUARE_LEAFLET.length + 1);
    expect(ring[0]).toEqual(ring[ring.length - 1]);
  });

  it('leaves an already-closed ring alone', () => {
    const closed: [number, number][] = [...SQUARE_LEAFLET, [CHENNAI_LAT, CHENNAI_LON]];
    const ring = leafletToRing(closed);

    expect(ring).toHaveLength(closed.length);
  });
});

describe('polygonFromLeaflet', () => {
  it('produces a GeoJSON Polygon with one exterior ring', () => {
    const polygon = polygonFromLeaflet(SQUARE_LEAFLET);

    expect(polygon.type).toBe('Polygon');
    expect(polygon.coordinates).toHaveLength(1);
  });
});

describe('approximateAreaSqFt', () => {
  it('computes an area of the expected magnitude', () => {
    // 0.0004 degrees is roughly 44 m at this latitude, so about 1,950 sq m,
    // which is roughly 21,000 sq ft.
    const polygon = polygonFromLeaflet(SQUARE_LEAFLET);

    expect(approximateAreaSqFt(polygon)).toBeGreaterThan(15_000);
    expect(approximateAreaSqFt(polygon)).toBeLessThan(28_000);
  });

  it('scales with the square of a linear dimension', () => {
    const small = polygonFromLeaflet(SQUARE_LEAFLET);
    const large = polygonFromLeaflet(
      SQUARE_LEAFLET.map(([lat, lon]) => [
        CHENNAI_LAT + (lat - CHENNAI_LAT) * 2,
        CHENNAI_LON + (lon - CHENNAI_LON) * 2,
      ])
    );

    expect(approximateAreaSqFt(large) / approximateAreaSqFt(small)).toBeCloseTo(4, 1);
  });
});
