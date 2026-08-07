/**
 * Smoke test that the app shell mounts.
 *
 * Exists because a module-level import error renders a blank page with no visible
 * clue — the exact failure this test would have caught. Rendering App here means
 * any future import-time crash fails the suite instead of shipping a white screen.
 */
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import App from './App';

describe('App', () => {
  it('mounts and renders the header', () => {
    // The catalogue request fires on mount; the global fetch guard in
    // test/setup.ts would throw, so it is stubbed to a pending promise here.
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise(() => {}))
    );

    render(<App />);

    expect(screen.getByRole('heading', { name: 'Climate Lien Score' })).toBeInTheDocument();
  });
});
