/**
 * Component tests for the material picker and the timeline slider.
 *
 * The map itself is not rendered here: Leaflet needs a real layout engine, and a
 * jsdom test of it would assert almost nothing. The map's actual logic —
 * coordinate conversion — is tested directly in `lib/geo.test.ts`.
 */
import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';

import { MaterialPicker } from '@/components/MaterialPicker';
import { ScoreTimeline } from '@/components/timeline/ScoreTimeline';
import type { MaterialCatalogue, YearBreakdown } from '@/types/api';

function material(code: string, name: string, component: 'foundation' | 'walls' | 'roofing') {
  return {
    code,
    name,
    component,
    resistance: { wind: 0.5, flood: 0.4, heat: 0.45 },
    relative_cost_index: 1,
    source_reference: 'BMTPC Vulnerability Atlas of India (3rd ed., 2019)',
    notes: null,
  };
}

const CATALOGUE: MaterialCatalogue = {
  foundation: [material('strip', 'Shallow strip footing', 'foundation')],
  walls: [
    material('brick', 'Fired clay brick masonry', 'walls'),
    material('aac', 'AAC block', 'walls'),
  ],
  roofing: [material('gi', 'Galvanised iron sheet roofing', 'roofing')],
};

describe('MaterialPicker', () => {
  it('renders a selector for every building component', () => {
    render(<MaterialPicker catalogue={CATALOGUE} selection={{}} onChange={vi.fn()} />);

    expect(screen.getByLabelText('Foundation')).toBeInTheDocument();
    expect(screen.getByLabelText('Walls')).toBeInTheDocument();
    expect(screen.getByLabelText('Roofing')).toBeInTheDocument();
  });

  it('lists every option for a component', () => {
    render(<MaterialPicker catalogue={CATALOGUE} selection={{}} onChange={vi.fn()} />);

    expect(screen.getByRole('option', { name: 'Fired clay brick masonry' })).toBeInTheDocument();
    expect(screen.getByRole('option', { name: 'AAC block' })).toBeInTheDocument();
  });

  it('reports the chosen code to its parent', async () => {
    const onChange = vi.fn();
    render(<MaterialPicker catalogue={CATALOGUE} selection={{}} onChange={onChange} />);

    await userEvent.selectOptions(screen.getByLabelText('Walls'), 'aac');

    expect(onChange).toHaveBeenCalledWith('walls', 'aac');
  });

  it('shows the published source for the selected material', () => {
    // An undocumented resistance rating is not something to ask a reader to trust.
    render(
      <MaterialPicker catalogue={CATALOGUE} selection={{ walls: 'brick' }} onChange={vi.fn()} />
    );

    expect(screen.getByText(/BMTPC Vulnerability Atlas/)).toBeInTheDocument();
  });
});

function years(damageByYear: Record<number, number>): YearBreakdown[] {
  return Object.entries(damageByYear).map(([year, damage]) => ({
    year: Number(year),
    peak_wind_speed_ms: 30,
    max_daily_rainfall_mm: 150,
    max_temperature_c: 38,
    max_wet_bulb_temperature_c: 28,
    intensity_wind: 0.6,
    intensity_flood: 0.7,
    intensity_heat: 0.95,
    stress_total: 0.5,
    damage_ratio: damage,
    damage_ratio_lower: Math.max(0, damage - 0.05),
    damage_ratio_upper: Math.min(1, damage + 0.05),
    is_uninsurable: damage >= 0.4,
    exceeds_survivability_limit: false,
  }));
}

describe('ScoreTimeline', () => {
  const SERIES = years({ 2025: 0.1, 2035: 0.3, 2045: 0.55 });

  it('shows the selected year', () => {
    render(
      <ScoreTimeline
        baselineYears={SERIES}
        threshold={0.4}
        selectedYear={2035}
        onSelectYear={vi.fn()}
      />
    );

    expect(screen.getByRole('slider')).toHaveValue('2035');
  });

  it('spans the full 2025 to 2055 horizon', () => {
    render(
      <ScoreTimeline
        baselineYears={SERIES}
        threshold={0.4}
        selectedYear={2025}
        onSelectYear={vi.fn()}
      />
    );

    const slider = screen.getByRole('slider');
    expect(slider).toHaveAttribute('min', '2025');
    expect(slider).toHaveAttribute('max', '2055');
  });

  it('reports a year change to its parent', () => {
    const onSelectYear = vi.fn();
    render(
      <ScoreTimeline
        baselineYears={SERIES}
        threshold={0.4}
        selectedYear={2025}
        onSelectYear={onSelectYear}
      />
    );

    // fireEvent.change rather than userEvent: dragging a range input has no
    // keyboard or pointer equivalent that jsdom simulates reliably.
    fireEvent.change(screen.getByRole('slider'), { target: { value: '2041' } });

    expect(onSelectYear).toHaveBeenCalledWith(2041);
  });

  it('shows the hazard figures for the selected year', () => {
    render(
      <ScoreTimeline
        baselineYears={SERIES}
        threshold={0.4}
        selectedYear={2045}
        onSelectYear={vi.fn()}
      />
    );

    expect(screen.getByText('55%')).toBeInTheDocument();
    expect(screen.getByText('30.0 m/s')).toBeInTheDocument();
  });
});
