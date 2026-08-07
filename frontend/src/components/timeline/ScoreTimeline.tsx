/**
 * The 2025–2055 timeline: a year slider and a red-to-green damage curve.
 *
 * When a baseline and an improved series are both present they are drawn on the
 * same axes, because the whole point of the prove step is that the two are
 * directly comparable — putting them in separate charts would invite a reader to
 * compare differently scaled pictures.
 */
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';

import { formatPercent } from '@/lib/format';
import { HORIZON_END_YEAR, HORIZON_START_YEAR, type YearBreakdown } from '@/types/api';

const BASELINE_COLOUR = '#dc2626';
const IMPROVED_COLOUR = '#16a34a';
const THRESHOLD_COLOUR = '#334155';

interface ChartRow {
  year: number;
  baseline: number;
  improved?: number;
}

export function ScoreTimeline({
  baselineYears,
  improvedYears,
  threshold,
  selectedYear,
  onSelectYear,
}: {
  baselineYears: YearBreakdown[];
  // Explicitly `| undefined`: with exactOptionalPropertyTypes, an optional prop
  // does not accept an explicitly-passed undefined unless it says so.
  improvedYears?: YearBreakdown[] | undefined;
  threshold: number;
  selectedYear: number;
  onSelectYear: (year: number) => void;
}) {
  const improvedByYear = new Map((improvedYears ?? []).map((entry) => [entry.year, entry]));

  const rows: ChartRow[] = baselineYears.map((entry) => {
    const improved = improvedByYear.get(entry.year);
    return improved === undefined
      ? { year: entry.year, baseline: entry.damage_ratio }
      : { year: entry.year, baseline: entry.damage_ratio, improved: improved.damage_ratio };
  });

  const selected = baselineYears.find((entry) => entry.year === selectedYear);

  return (
    <div className="space-y-4">
      <div className="h-64">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={rows} margin={{ top: 8, right: 12, bottom: 8, left: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e2e8f0" />
            <XAxis dataKey="year" tick={{ fontSize: 12 }} stroke="#64748b" />
            <YAxis
              domain={[0, 1]}
              tickFormatter={(value: number) => formatPercent(value)}
              tick={{ fontSize: 12 }}
              stroke="#64748b"
            />
            <Tooltip
              formatter={(value: number, name: string) => [formatPercent(value), name]}
              labelFormatter={(label: number) => `Year ${String(label)}`}
            />
            {/* The threshold is drawn explicitly so the crossing is visible rather
                than something the reader has to infer from the numbers. */}
            <ReferenceLine
              y={threshold}
              stroke={THRESHOLD_COLOUR}
              strokeDasharray="4 4"
              label={{ value: 'Uninsurable', position: 'right', fontSize: 11 }}
            />
            <ReferenceLine x={selectedYear} stroke="#94a3b8" />
            <Line
              type="monotone"
              dataKey="baseline"
              name="Your materials"
              stroke={BASELINE_COLOUR}
              strokeWidth={2}
              dot={false}
            />
            {improvedYears !== undefined && (
              <Line
                type="monotone"
                dataKey="improved"
                name="Suggested materials"
                stroke={IMPROVED_COLOUR}
                strokeWidth={2}
                dot={false}
              />
            )}
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div>
        <label htmlFor="year-slider" className="block text-sm font-medium text-slate-700">
          Year: <span className="font-semibold">{selectedYear}</span>
        </label>
        <input
          id="year-slider"
          type="range"
          min={HORIZON_START_YEAR}
          max={HORIZON_END_YEAR}
          step={1}
          value={selectedYear}
          onChange={(event) => {
            onSelectYear(Number(event.target.value));
          }}
          className="mt-2 w-full accent-slate-900"
        />
        {selected !== undefined && (
          <dl className="mt-3 grid grid-cols-2 gap-3 text-sm sm:grid-cols-4">
            <div>
              <dt className="text-slate-500">Damage</dt>
              <dd className="font-medium">{formatPercent(selected.damage_ratio)}</dd>
            </div>
            <div>
              <dt className="text-slate-500">Peak wind</dt>
              <dd className="font-medium">{selected.peak_wind_speed_ms.toFixed(1)} m/s</dd>
            </div>
            <div>
              <dt className="text-slate-500">Max rainfall</dt>
              <dd className="font-medium">{selected.max_daily_rainfall_mm.toFixed(0)} mm/day</dd>
            </div>
            <div>
              <dt className="text-slate-500">Max temp</dt>
              <dd className="font-medium">{selected.max_temperature_c.toFixed(1)} °C</dd>
            </div>
          </dl>
        )}
      </div>
    </div>
  );
}
