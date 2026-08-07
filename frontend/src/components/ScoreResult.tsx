/**
 * The score, its breakdown, and the before/after comparison.
 *
 * Everything shown here comes from the API response. Nothing is recomputed on the
 * client, so what the user reads is exactly what the engine recorded and what the
 * report describes.
 */
import { useState } from 'react';

import { ScoreTimeline } from '@/components/timeline/ScoreTimeline';
import { Stat } from '@/components/ui';
import {
  formatComponent,
  formatCrossingYear,
  formatPercent,
  formatYearRange,
  riskBand,
  riskTextClass,
} from '@/lib/format';
import { HORIZON_START_YEAR, type ProveResponse, type ScoreResponse } from '@/types/api';

function CrossingYear({ score, label }: { score: ScoreResponse; label: string }) {
  return (
    <Stat
      label={label}
      value={formatCrossingYear(score.crossing_year)}
      accent={riskTextClass(riskBand(score.crossing_year))}
    />
  );
}

export function ScoreResult({
  score,
  proof,
}: {
  score: ScoreResponse;
  proof: ProveResponse | null;
}) {
  const [selectedYear, setSelectedYear] = useState<number>(
    score.crossing_year ?? HORIZON_START_YEAR
  );

  const survivability = score.breakdown.years.some(
    (year) => year.exceeds_survivability_limit
  );

  return (
    <div className="space-y-6">
      <div className="flex flex-wrap items-end gap-8">
        <CrossingYear score={score} label="Climate Lien Score" />
        {proof !== null && <CrossingYear score={proof.improved} label="With suggested materials" />}
        <Stat label="Confidence" value={score.confidence} />
        <Stat
          label="Range"
          value={formatYearRange(score.crossing_year_lower, score.crossing_year_upper)}
        />
      </div>

      {score.crossing_year === null && (
        <p className="rounded-md border border-emerald-300 bg-emerald-50 p-3 text-sm text-emerald-900">
          This site stays below the uninsurability threshold for the whole 2025–2055
          horizon under this projection.
        </p>
      )}

      {survivability && (
        <p className="rounded-md border border-red-300 bg-red-50 p-3 text-sm text-red-900">
          Projected wet-bulb temperature exceeds the 35 °C human survivability limit in
          at least one year. No choice of construction material mitigates this.
        </p>
      )}

      <ScoreTimeline
        baselineYears={score.breakdown.years}
        improvedYears={proof?.improved.breakdown.years}
        threshold={score.breakdown.uninsurable_damage_threshold}
        selectedYear={selectedYear}
        onSelectYear={setSelectedYear}
      />

      <div>
        <h3 className="mb-2 text-sm font-semibold text-slate-900">
          Where the stress goes
          <span className="ml-2 font-normal text-slate-500">
            (at {formatCrossingYear(score.crossing_year)})
          </span>
        </h3>
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-500">
              <th className="py-2">Component</th>
              <th className="py-2">Material</th>
              <th className="py-2 text-right">Wind</th>
              <th className="py-2 text-right">Flood</th>
              <th className="py-2 text-right">Heat</th>
              <th className="py-2 text-right">Total</th>
            </tr>
          </thead>
          <tbody>
            {score.breakdown.components.map((component) => {
              const byHazard = new Map(
                component.by_hazard.map((entry) => [entry.hazard, entry.contribution])
              );
              return (
                <tr key={component.component} className="border-b border-slate-100">
                  <td className="py-2 font-medium">{formatComponent(component.component)}</td>
                  <td className="py-2 text-slate-600">{component.material_name}</td>
                  <td className="py-2 text-right tabular-nums">
                    {(byHazard.get('wind') ?? 0).toFixed(3)}
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {(byHazard.get('flood') ?? 0).toFixed(3)}
                  </td>
                  <td className="py-2 text-right tabular-nums">
                    {(byHazard.get('heat') ?? 0).toFixed(3)}
                  </td>
                  <td className="py-2 text-right font-medium tabular-nums">
                    {component.total.toFixed(3)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {proof !== null && proof.recommendations.length > 0 && (
        <div>
          <h3 className="mb-2 text-sm font-semibold text-slate-900">Suggested changes</h3>
          <ul className="space-y-2">
            {proof.recommendations.map((recommendation) => (
              <li
                key={recommendation.component}
                className="rounded-md border border-slate-200 bg-slate-50 p-3 text-sm"
              >
                <p className="font-medium">
                  {formatComponent(recommendation.component)}:{' '}
                  <span className="text-slate-500 line-through">
                    {recommendation.current_name}
                  </span>{' '}
                  → {recommendation.recommended_name}
                </p>
                <p className="mt-1 text-slate-600">{recommendation.rationale}</p>
                <p className="mt-1 text-xs text-slate-500">
                  Removes {formatPercent(recommendation.predicted_damage_reduction)} of damage ·
                  relative cost {recommendation.relative_cost_index.toFixed(2)}×
                </p>
              </li>
            ))}
          </ul>
          {proof.years_gained !== null && (
            <p className="mt-3 text-sm font-medium text-emerald-700">
              These changes move the crossing year {proof.years_gained} year
              {proof.years_gained === 1 ? '' : 's'} later.
            </p>
          )}
        </div>
      )}

      <p className="border-t border-slate-200 pt-3 text-xs text-slate-500">
        Damage model {score.damage_model_version} · ranking model{' '}
        {score.material_model_version} · threshold{' '}
        {formatPercent(score.breakdown.uninsurable_damage_threshold)} damage ratio
      </p>
    </div>
  );
}
