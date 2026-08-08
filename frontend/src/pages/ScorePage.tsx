/**
 * Step 5 — the result.
 *
 * The score is fetched here, on mount, from the session's specification. It is
 * deliberately not cached in the session: coming back to this page after editing an
 * input must re-score, never show a stale number beside changed inputs.
 */
import { motion, useReducedMotion } from 'motion/react';
import { useCallback, useEffect, useState } from 'react';
import { useNavigate } from 'react-router-dom';

import { PageShell } from '@/components/Shell';
import { ScoreComparison } from '@/components/ScoreComparison';
import { Button, ErrorNotice, Panel, Popup, Spinner } from '@/components/ui';
import { useAction } from '@/hooks/useAction';
import { apiClient } from '@/lib/api-client';
import { formatParameter, formatPercent } from '@/lib/format';
import { useSession, type SiteSpecification } from '@/state/session-context';
import type { ClimateProvenance, MaterialSelectionInput, ScoreResponse } from '@/types/api';

/**
 * The materials payload, or null.
 *
 * Null is meaningful to the API: it means "recommend rather than evaluate". Derived
 * in one place so the score request and the report request cannot disagree.
 */
function materialsPayload(spec: SiteSpecification): MaterialSelectionInput | null {
  return spec.evaluateOwnMaterials
    ? {
        concrete: spec.concrete,
        walling_material_id: spec.wallingMaterialId,
        element_situation: spec.situation,
      }
    : null;
}

export default function ScorePage() {
  const { spec, area } = useSession();
  const navigate = useNavigate();
  const reduced = useReducedMotion();
  const [result, setResult] = useState<ScoreResponse | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [climateOpen, setClimateOpen] = useState(false);

  const report = useAction(apiClient.downloadReport.bind(apiClient));

  useEffect(() => {
    let cancelled = false;
    setResult(null);
    setError(null);
    // A drawn boundary and a named district are different endpoints, because only
    // the area one can report whether its climate was interpolated.
    const pending =
      area !== null
        ? apiClient.scoreArea(area, materialsPayload(spec), spec.situation)
        : apiClient.score(spec.district, materialsPayload(spec), spec.situation);

    pending
      .then((response) => {
        if (!cancelled) {
          setResult(response);
        }
      })
      .catch((cause: unknown) => {
        if (!cancelled) {
          setError(cause);
        }
      });
    return () => {
      cancelled = true;
    };
  }, [spec, area]);

  const handleDownload = useCallback(async () => {
    const blob = await report.run(spec.district, materialsPayload(spec), spec.situation);
    if (blob === null) {
      return;
    }
    // Anchor-and-revoke: the browser needs a URL to save from, and the object URL
    // must be released or the blob stays in memory for the page's lifetime.
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = `building-quality-score-${spec.district.toLowerCase()}.pdf`;
    anchor.click();
    URL.revokeObjectURL(url);
  }, [spec, report]);

  return (
    <PageShell
      eyebrow="Step 5 of 5"
      title={`${spec.district}, scored`}
      lead={
        result === null
          ? undefined
          : `${result.exposure_label} exposure, from climate measured on the ground rather than modelled.`
      }
      wide
    >
      {result === null && error === null && (
        <Panel className="p-10">
          <Spinner label="Checking your specification against IS 456…" />
        </Panel>
      )}

      {error !== null && (
        <div className="space-y-5">
          <ErrorNotice error={error} />
          <Button
            variant="secondary"
            onClick={() => {
              void navigate('/materials');
            }}
          >
            Go back and change something
          </Button>
        </div>
      )}

      {result !== null && (
        <div className="space-y-6">
          {/* Placed above the score, not below it. An interpolated reading must
              qualify the number before it is read, not footnote it afterwards. */}
          {result.climate_provenance != null && (
            <ProvenanceNotice provenance={result.climate_provenance} />
          )}

          <ScoreComparison
            proposed={result.proposed}
            recommended={result.recommended}
            improvement={result.improvement}
            evaluatedOwnMaterials={spec.evaluateOwnMaterials}
          />

          <Panel className="p-6">
            <div className="flex flex-wrap items-baseline justify-between gap-3">
              <h2 className="text-base font-semibold text-ink-1">
                Your site is {result.exposure_label.toLowerCase()} exposure
              </h2>
              <button
                type="button"
                onClick={() => {
                  setClimateOpen(true);
                }}
                className="text-sm font-medium text-atmos underline underline-offset-4"
              >
                See the measurements
              </button>
            </div>
            <ul className="mt-3 space-y-1.5 text-sm text-ink-2">
              {result.exposure_reasons.map((reason) => (
                <li key={reason} className="flex gap-2.5">
                  <span aria-hidden="true" className="text-ink-3">
                    —
                  </span>
                  {reason}
                </li>
              ))}
            </ul>
          </Panel>

          <Panel className="p-6">
            <h2 className="text-base font-semibold text-ink-1">What we checked</h2>
            <div className="mt-4 overflow-x-auto">
              <table className="w-full min-w-[28rem] text-left text-sm">
                <thead>
                  <tr className="border-b border-white/10 text-[11px] uppercase tracking-[0.12em] text-ink-3">
                    <th className="pb-2.5 font-medium">Requirement</th>
                    <th className="pb-2.5 text-right font-medium">Code needs</th>
                    <th className="pb-2.5 text-right font-medium">You have</th>
                    <th className="pb-2.5 text-right font-medium">Result</th>
                  </tr>
                </thead>
                <tbody>
                  {result.proposed.findings.map((finding, index) => (
                    <motion.tr
                      key={finding.parameter}
                      className="border-b border-white/[0.06]"
                      initial={reduced === true ? false : { opacity: 0, x: -8 }}
                      animate={{ opacity: 1, x: 0 }}
                      transition={
                        reduced === true ? { duration: 0 } : { delay: 0.05 * index, duration: 0.3 }
                      }
                    >
                      <td className="py-2.5 text-ink-1">{formatParameter(finding.parameter)}</td>
                      <td className="tabular py-2.5 text-right text-ink-2">{finding.required}</td>
                      <td className="tabular py-2.5 text-right text-ink-2">{finding.provided}</td>
                      <td
                        className={`py-2.5 text-right font-semibold ${
                          finding.compliant ? 'text-band-good' : 'text-band-poor'
                        }`}
                      >
                        {finding.compliant ? 'Meets' : 'Short'}
                      </td>
                    </motion.tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Panel>

          {result.recommendations.length > 0 && (
            <Panel className="p-6">
              <h2 className="text-base font-semibold text-ink-1">
                Recommended for this climate
              </h2>
              <ul className="mt-4 space-y-4">
                {result.recommendations.map((recommendation) => (
                  <li key={recommendation.id} className="text-sm">
                    <p className="font-semibold text-ink-1">
                      {recommendation.material}
                      {recommendation.followed && (
                        <span className="ml-2 text-xs font-medium text-band-good">
                          already in your spec
                        </span>
                      )}
                    </p>
                    <p className="mt-0.5 text-ink-2">{recommendation.purpose}</p>
                    <p className="mt-0.5 text-xs text-ink-3">{recommendation.standard}</p>
                  </li>
                ))}
              </ul>
            </Panel>
          )}

          <Panel className="p-6">
            <h2 className="text-base font-semibold text-ink-1">Take this with you</h2>
            <p className="mt-1 text-sm leading-relaxed text-ink-2">
              A one-page summary you can hand to your contractor, with the
              specification and the code clause behind each item.
            </p>
            <div className="mt-4 flex flex-wrap gap-3">
              <Button
                onClick={() => {
                  void handleDownload();
                }}
                disabled={report.loading}
              >
                {report.loading ? 'Preparing…' : 'Download the report (PDF)'}
              </Button>
              <Button
                variant="secondary"
                onClick={() => {
                  void navigate('/materials');
                }}
              >
                Change my materials
              </Button>
            </div>
            {report.error !== null && (
              <div className="mt-4">
                <ErrorNotice error={report.error} />
              </div>
            )}
          </Panel>

          <p className="text-xs leading-relaxed text-ink-3">
            Score computed by {result.model_version}, from IS 456 compliance margins.
            It reflects code compliance against measured climate — it is not a
            prediction of whether a building will fail.
          </p>

          <Popup
            open={climateOpen}
            title={`Measured climate for ${result.district}`}
            description={`${result.data_source['dataset'] ?? 'Reanalysis'}, ${String(result.climate.observation_days)} days observed.`}
            onClose={() => {
              setClimateOpen(false);
            }}
          >
            <dl className="grid grid-cols-2 gap-5">
              <Measurement
                label="Mean humidity"
                value={`${result.climate.mean_relative_humidity_percent.toFixed(0)}%`}
              />
              <Measurement
                label="Mean peak temp"
                value={`${result.climate.mean_max_temperature_c.toFixed(1)} °C`}
              />
              <Measurement
                label="Distance from coast"
                value={`${result.climate.distance_to_coast_km.toFixed(0)} km`}
              />
              <Measurement
                label="Peak wind gust"
                value={`${result.climate.max_wind_gust_ms.toFixed(1)} m/s`}
              />
              <Measurement
                label="Wet hours"
                value={formatPercent(result.climate.wet_hours_fraction)}
              />
              <Measurement
                label="Wet/dry cycles"
                value={`${result.climate.wet_dry_cycles_per_year.toFixed(0)} /yr`}
              />
            </dl>
            <p className="mt-6 border-t border-white/10 pt-4 text-xs leading-relaxed text-ink-3">
              Observed {result.data_source['observation_start'] ?? '—'} to{' '}
              {result.data_source['observation_end'] ?? '—'}. Wet hours is the fraction
              of sampled hours with rainfall, used instead of an annual total because
              the source accumulates over one hour per day — an annual depth would
              require assuming a daily cycle the data does not contain.
            </p>
          </Popup>
        </div>
      )}
    </PageShell>
  );
}

/**
 * Says how the climate behind an area score was arrived at.
 *
 * Two genuinely different statements, not one hedge: a boundary containing measured
 * cells gets a plain confirmation, while one that fell between cells is explicitly
 * marked as derived and names the cells it was derived from. Collapsing these into a
 * single vague caveat would make the honest case look doubtful and the derived case
 * look measured.
 */
function ProvenanceNotice({ provenance }: { provenance: ClimateProvenance }) {
  if (!provenance.interpolated) {
    return (
      <p className="rounded-xl border border-band-good/30 bg-band-good/[0.07] px-4 py-3 text-sm text-ink-2">
        <span className="font-semibold text-band-good">Measured.</span> Your boundary
        contains {provenance.enclosed_node_count} measured climate{' '}
        {provenance.enclosed_node_count === 1 ? 'cell' : 'cells'}
        {provenance.enclosed_node_count === 1 ? '' : ', combined'} — nothing below was
        estimated.
      </p>
    );
  }

  return (
    <div className="rounded-xl border border-signal/40 bg-signal/[0.08] px-4 py-3 text-sm">
      <p className="font-semibold text-signal">Estimated for this location</p>
      <p className="mt-1 leading-relaxed text-ink-2">
        No measured cell falls inside your boundary, so the climate below was
        interpolated from the {provenance.source_districts.length} nearest measured{' '}
        {provenance.source_districts.length === 1 ? 'cell' : 'cells'} —{' '}
        {provenance.source_districts.join(', ')} — with closer cells weighted more
        heavily. The nearest is {provenance.nearest_source_km.toFixed(0)} km away.
      </p>
      <p className="mt-2 text-xs leading-relaxed text-ink-3">
        This is interpolation between real readings, not invention. Treat the result
        as indicative and confirm against site data before it informs a permit.
      </p>
    </div>
  );
}

function Measurement({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-[11px] uppercase tracking-[0.12em] text-ink-3">{label}</dt>
      <dd className="tabular mt-1 text-xl font-semibold text-ink-1">{value}</dd>
    </div>
  );
}
