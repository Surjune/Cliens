/**
 * Loads Leaflet and its draw plugin in the right order.
 *
 * `leaflet-draw` is a pre-ES-module script: it attaches itself to a **global** `L`
 * and throws `ReferenceError: L is not defined` when loaded through a bundler,
 * because an ESM import gives it no global to attach to. The symptom is a blank
 * page with the error only visible in the browser console.
 *
 * The fix has to respect ESM evaluation order. Static imports are hoisted, so
 * assigning `window.L` in the same module as `import 'leaflet-draw'` would still
 * run too late. Splitting it across two modules works because sibling imports are
 * evaluated in source order: `./leaflet-global` completes — setting `window.L` —
 * before `leaflet-draw` is evaluated.
 *
 * Import this module instead of `leaflet` anywhere the draw controls are needed.
 */
import L from './leaflet-global';
import 'leaflet-draw';

export default L;
