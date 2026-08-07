/**
 * Display formatting, defined once so the same quantity never appears two ways.
 */
import { HORIZON_END_YEAR } from '@/types/api';

const AREA_FORMAT = new Intl.NumberFormat('en-IN', { maximumFractionDigits: 0 });

/** Format a floor area with its unit. */
export function formatArea(sqFt: number): string {
  return `${AREA_FORMAT.format(sqFt)} sq ft`;
}

/**
 * Render a crossing year for display.
 *
 * `null` means the site never crosses the threshold within the horizon, which is
 * materially different from crossing in the final year and must never be
 * collapsed into it.
 */
export function formatCrossingYear(year: number | null): string {
  return year === null ? `Beyond ${String(HORIZON_END_YEAR)}` : String(year);
}

/** Render the uncertainty range around a crossing year. */
export function formatYearRange(lower: number | null, upper: number | null): string {
  if (lower === null && upper === null) {
    return 'no crossing projected in range';
  }
  return `${formatCrossingYear(lower)} – ${formatCrossingYear(upper)}`;
}

/** Format a damage ratio as a percentage. */
export function formatPercent(ratio: number): string {
  return `${(ratio * 100).toFixed(0)}%`;
}

/** Human-readable label for a building component. */
export function formatComponent(component: string): string {
  return component.charAt(0).toUpperCase() + component.slice(1);
}

/**
 * Map a crossing year to a risk band, for the red-to-green transition.
 *
 * Bands are relative to the horizon: crossing soon is critical, surviving the
 * whole horizon is minimal.
 */
export function riskBand(year: number | null): 'critical' | 'high' | 'moderate' | 'low' | 'minimal' {
  if (year === null) {
    return 'minimal';
  }
  if (year <= 2030) {
    return 'critical';
  }
  if (year <= 2038) {
    return 'high';
  }
  if (year <= 2046) {
    return 'moderate';
  }
  return 'low';
}

/** Tailwind text colour class for a risk band. */
export function riskTextClass(band: ReturnType<typeof riskBand>): string {
  return {
    critical: 'text-risk-critical',
    high: 'text-risk-high',
    moderate: 'text-risk-moderate',
    low: 'text-risk-low',
    minimal: 'text-risk-minimal',
  }[band];
}
