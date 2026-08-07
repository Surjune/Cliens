/**
 * Map with a polygon draw tool for selecting a building site.
 *
 * Leaflet.draw is attached imperatively through `useMap` rather than via a React
 * wrapper: the maintained wrappers for Leaflet.draw have not kept pace with
 * React 19, and the imperative surface here is small and well contained.
 *
 * Coordinate conversion is delegated to `lib/geo` — this component never reorders
 * a coordinate pair itself.
 */
import { useEffect } from 'react';
import { MapContainer, TileLayer, useMap } from 'react-leaflet';

import { approximateAreaSqFt, polygonFromLeaflet } from '@/lib/geo';
// Not `from 'leaflet'`: leaflet-draw needs a global L, which this module sets up.
import L from '@/lib/leaflet-setup';
import type { PolygonGeometry } from '@/types/api';

/** Chennai, near the Adyar estuary — the Cyclone Michaung framing. */
const DEFAULT_CENTRE: [number, number] = [13.01, 80.27];
const DEFAULT_ZOOM = 15;

/** Leaflet's marker icons resolve to broken URLs under a bundler by default. */
const DRAW_STYLE = { color: '#0f172a', weight: 2, fillOpacity: 0.15 };

function DrawControl({
  onPolygonDrawn,
}: {
  onPolygonDrawn: (geometry: PolygonGeometry, approximateAreaSqFt: number) => void;
}) {
  const map = useMap();

  useEffect(() => {
    const drawnItems = new L.FeatureGroup();
    map.addLayer(drawnItems);

    const control = new L.Control.Draw({
      position: 'topright',
      draw: {
        polygon: { allowIntersection: false, shapeOptions: DRAW_STYLE },
        // Only polygons make sense as a building footprint.
        rectangle: false,
        circle: false,
        circlemarker: false,
        marker: false,
        polyline: false,
      },
      edit: { featureGroup: drawnItems, remove: true },
    });
    map.addControl(control);

    const handleCreated = (event: L.LeafletEvent) => {
      // Only one site at a time: drawing again replaces the previous outline
      // rather than silently accumulating shapes.
      drawnItems.clearLayers();

      const layer = (event as unknown as { layer: L.Polygon }).layer;
      drawnItems.addLayer(layer);

      const latLngs = layer.getLatLngs()[0] as L.LatLng[];
      const points: [number, number][] = latLngs.map((point) => [point.lat, point.lng]);
      const geometry = polygonFromLeaflet(points);

      onPolygonDrawn(geometry, approximateAreaSqFt(geometry));
    };

    map.on(L.Draw.Event.CREATED, handleCreated);
    map.on(L.Draw.Event.EDITED, () => {
      const layers = drawnItems.getLayers();
      const first = layers[0];
      if (first instanceof L.Polygon) {
        const latLngs = first.getLatLngs()[0] as L.LatLng[];
        const points: [number, number][] = latLngs.map((point) => [point.lat, point.lng]);
        const geometry = polygonFromLeaflet(points);
        onPolygonDrawn(geometry, approximateAreaSqFt(geometry));
      }
    });

    return () => {
      map.off(L.Draw.Event.CREATED, handleCreated);
      map.removeControl(control);
      map.removeLayer(drawnItems);
    };
  }, [map, onPolygonDrawn]);

  return null;
}

export function SiteMap({
  onPolygonDrawn,
}: {
  onPolygonDrawn: (geometry: PolygonGeometry, approximateAreaSqFt: number) => void;
}) {
  return (
    <div className="h-[420px] overflow-hidden rounded-md border border-slate-200">
      <MapContainer
        center={DEFAULT_CENTRE}
        zoom={DEFAULT_ZOOM}
        scrollWheelZoom
        className="h-full w-full"
      >
        <TileLayer
          // OpenStreetMap needs no access token, so the app runs on a clean clone
          // with no third-party signup. Attribution is required by their licence.
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <DrawControl onPolygonDrawn={onPolygonDrawn} />
      </MapContainer>
    </div>
  );
}
