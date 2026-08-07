/**
 * Vitest global setup.
 *
 * Registers jest-dom matchers and installs guards that make it impossible for a
 * test to silently reach the network — the brief requires that external services
 * are always mocked.
 */
// Matchers are registered explicitly rather than via '@testing-library/jest-dom/vitest'.
// That entry point does a bare `import 'vitest'`, and npm hoists jest-dom to the
// workspace root while vitest stays in frontend/node_modules — so the bare import
// cannot resolve. Extending expect directly sidesteps the hoisting entirely.
import * as matchers from '@testing-library/jest-dom/matchers';
import { cleanup } from '@testing-library/react';
import { afterEach, beforeAll, expect, vi } from 'vitest';

expect.extend(matchers);

beforeAll(() => {
  // Any test that needs HTTP must mock `fetch` explicitly. An unmocked call
  // fails loudly here rather than hanging or hitting a real server.
  vi.stubGlobal(
    'fetch',
    vi.fn(() => {
      throw new Error(
        'Unmocked fetch() in a test. Mock the API client or stub fetch for this case.'
      );
    })
  );

  // Recharts' ResponsiveContainer observes its parent's size. jsdom implements
  // no ResizeObserver, so a minimal stand-in is installed; combined with the
  // fixed dimensions below, charts render at a deterministic size.
  vi.stubGlobal(
    'ResizeObserver',
    class {
      observe(): void {
        // No layout engine in jsdom, so there is nothing to observe.
      }
      unobserve(): void {
        // Intentionally empty.
      }
      disconnect(): void {
        // Intentionally empty.
      }
    }
  );

  // Leaflet measures its container during initialisation. jsdom reports every
  // element as 0x0, which makes the map throw, so give it a deterministic size.
  Object.defineProperty(HTMLElement.prototype, 'clientWidth', {
    configurable: true,
    value: 1024,
  });
  Object.defineProperty(HTMLElement.prototype, 'clientHeight', {
    configurable: true,
    value: 768,
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
