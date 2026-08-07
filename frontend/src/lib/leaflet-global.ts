/**
 * Publishes Leaflet on `window` so pre-ES-module plugins can find it.
 *
 * Deliberately a separate module from `leaflet-setup`: see the explanation of ESM
 * evaluation order there. Nothing should import this directly — import
 * `leaflet-setup` instead, which guarantees the plugin is loaded too.
 */
import L from 'leaflet';

declare global {
  interface Window {
    L: typeof L;
  }
}

window.L = L;

export default L;
