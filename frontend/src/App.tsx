/**
 * Application shell: draw a site, choose materials, score it, read the report.
 *
 * Every value displayed comes from a real API response. There is no mock data
 * anywhere in this build — when a dependency is unconfigured the UI shows the
 * backend's typed error rather than inventing a plausible number.
 */
import { useCallback, useState } from 'react';

import { MaterialPicker } from '@/components/MaterialPicker';
import { SiteMap } from '@/components/map/SiteMap';
import { ScoreResult } from '@/components/ScoreResult';
import { Button, Card, ErrorNotice, Spinner } from '@/components/ui';
import { useAction, useMaterials } from '@/hooks/useMaterials';
import { apiClient } from '@/lib/api-client';
import { formatArea } from '@/lib/format';
import {
  BUILDING_COMPONENTS,
  type BuildingComponent,
  type MaterialSelection,
  type PolygonGeometry,
  type ProveResponse,
  type ReportResponse,
  type ScoreResponse,
  type SiteResponse,
} from '@/types/api';

export default function App() {
  const catalogue = useMaterials();

  const [drawn, setDrawn] = useState<{ geometry: PolygonGeometry; areaSqFt: number } | null>(null);
  const [site, setSite] = useState<SiteResponse | null>(null);
  const [selection, setSelection] = useState<Partial<MaterialSelection>>({});
  const [score, setScore] = useState<ScoreResponse | null>(null);
  const [proof, setProof] = useState<ProveResponse | null>(null);
  const [report, setReport] = useState<ReportResponse | null>(null);

  const submitSite = useAction(apiClient.createSite.bind(apiClient));
  const runScore = useAction(apiClient.prove.bind(apiClient));
  const runReport = useAction(apiClient.createReport.bind(apiClient));

  const handlePolygon = useCallback((geometry: PolygonGeometry, areaSqFt: number) => {
    setDrawn({ geometry, areaSqFt });
    // A new outline invalidates everything downstream of it.
    setSite(null);
    setScore(null);
    setProof(null);
    setReport(null);
  }, []);

  const handleSubmitSite = async () => {
    if (drawn === null) {
      return;
    }
    const created = await submitSite.run({ geometry: drawn.geometry, label: null });
    if (created !== null) {
      setSite(created);
    }
  };

  const isComplete = BUILDING_COMPONENTS.every((component) => selection[component] !== undefined);

  const handleScore = async () => {
    if (site === null || !isComplete) {
      return;
    }
    const result = await runScore.run(site.id, selection as MaterialSelection);
    if (result !== null) {
      setProof(result);
      setScore(result.baseline);
      setReport(null);
    }
  };

  const handleReport = async () => {
    if (score === null) {
      return;
    }
    const generated = await runReport.run(score.id);
    if (generated !== null) {
      setReport(generated);
    }
  };

  return (
    <div className="min-h-full bg-slate-50 text-slate-900">
      <header className="border-b border-slate-200 bg-white px-6 py-4">
        <h1 className="text-xl font-semibold tracking-tight">Climate Lien Score</h1>
        <p className="text-sm text-slate-600">
          The year a building site crosses an uninsurable climate risk threshold.
        </p>
      </header>

      <main className="mx-auto grid max-w-6xl gap-6 p-6 lg:grid-cols-[1.4fr_1fr]">
        <div className="space-y-6">
          <Card title="Draw the site boundary" step={1}>
            <SiteMap onPolygonDrawn={handlePolygon} />
            {drawn !== null && (
              <div className="mt-4 flex flex-wrap items-center gap-4">
                <p className="text-sm text-slate-600">
                  Approximately {formatArea(drawn.areaSqFt)} — the exact figure is computed by
                  the server.
                </p>
                <Button
                  onClick={() => {
                    // `void`: the handler is async, but a click handler must
                    // return void. Errors are captured by useAction, not thrown.
                    void handleSubmitSite();
                  }}
                  disabled={submitSite.loading || site !== null}
                >
                  {site === null ? 'Use this boundary' : 'Boundary saved'}
                </Button>
              </div>
            )}
            {submitSite.loading && <Spinner label="Saving boundary…" />}
            {submitSite.error !== null && (
              <div className="mt-3">
                <ErrorNotice error={submitSite.error} />
              </div>
            )}
            {site !== null && (
              <p className="mt-3 text-sm text-emerald-700">
                Saved. Server-computed area: {formatArea(site.area_sq_ft)}.
              </p>
            )}
          </Card>

          {score !== null && (
            <Card title="Result">
              <ScoreResult score={score} proof={proof} />
            </Card>
          )}

          {score !== null && (
            <Card title="Plain-English report">
              {report === null ? (
                <div className="space-y-3">
                  <Button
                    onClick={() => {
                      void handleReport();
                    }}
                    disabled={runReport.loading}
                  >
                    Generate report
                  </Button>
                  {runReport.loading && <Spinner label="Writing the report…" />}
                  {runReport.error !== null && <ErrorNotice error={runReport.error} />}
                </div>
              ) : (
                <article className="whitespace-pre-wrap text-sm leading-relaxed text-slate-800">
                  {report.content}
                  <p className="mt-4 border-t border-slate-200 pt-3 text-xs text-slate-500">
                    Generated by {report.model_name} using prompt {report.prompt_version}.
                  </p>
                </article>
              )}
            </Card>
          )}
        </div>

        <div className="space-y-6">
          <Card title="Choose materials" step={2}>
            {catalogue.loading && <Spinner label="Loading materials…" />}
            {catalogue.error !== null && <ErrorNotice error={catalogue.error} />}
            {catalogue.data !== null && (
              <MaterialPicker
                catalogue={catalogue.data}
                selection={selection}
                onChange={(component: BuildingComponent, code: string) => {
                  setSelection((current) => ({ ...current, [component]: code }));
                }}
              />
            )}
          </Card>

          <Card title="Score the site" step={3}>
            <Button
              onClick={() => {
                void handleScore();
              }}
              disabled={site === null || !isComplete || runScore.loading}
            >
              Calculate Climate Lien Score
            </Button>
            {site === null && (
              <p className="mt-2 text-sm text-slate-500">Draw and save a boundary first.</p>
            )}
            {site !== null && !isComplete && (
              <p className="mt-2 text-sm text-slate-500">Choose a material for every component.</p>
            )}
            {runScore.loading && (
              <div className="mt-3">
                <Spinner label="Scoring — this queries climate projections…" />
              </div>
            )}
            {runScore.error !== null && (
              <div className="mt-3">
                <ErrorNotice error={runScore.error} />
              </div>
            )}
          </Card>
        </div>
      </main>
    </div>
  );
}
