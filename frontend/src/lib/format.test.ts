/**
 * Tests for display formatting.
 *
 * The critical case is a null crossing year: "never crosses within the horizon" is
 * materially different from "crosses in 2055" and must never be collapsed into it.
 */
import { describe, expect, it } from 'vitest';

import { formatArea, formatCrossingYear, formatPercent, formatYearRange, riskBand } from './format';

describe('formatCrossingYear', () => {
  it('renders a year as itself', () => {
    expect(formatCrossingYear(2041)).toBe('2041');
  });

  it('distinguishes "never crosses" from the final year', () => {
    expect(formatCrossingYear(null)).toBe('Beyond 2055');
    expect(formatCrossingYear(null)).not.toBe('2055');
  });
});

describe('formatYearRange', () => {
  it('renders both bounds', () => {
    expect(formatYearRange(2038, 2044)).toBe('2038 – 2044');
  });

  it('states plainly when no crossing is projected', () => {
    expect(formatYearRange(null, null)).toBe('no crossing projected in range');
  });
});

describe('formatPercent', () => {
  it('renders a ratio as a whole percentage', () => {
    expect(formatPercent(0.4)).toBe('40%');
    expect(formatPercent(0)).toBe('0%');
    expect(formatPercent(1)).toBe('100%');
  });
});

describe('formatArea', () => {
  it('includes the unit', () => {
    expect(formatArea(2000)).toContain('sq ft');
  });
});

describe('riskBand', () => {
  it('treats surviving the horizon as minimal risk', () => {
    expect(riskBand(null)).toBe('minimal');
  });

  it('treats an imminent crossing as critical', () => {
    expect(riskBand(2027)).toBe('critical');
  });

  it('moves through the bands as the year gets later', () => {
    expect(riskBand(2035)).toBe('high');
    expect(riskBand(2042)).toBe('moderate');
    expect(riskBand(2052)).toBe('low');
  });
});
