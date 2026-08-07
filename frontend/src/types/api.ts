/**
 * Convenient aliases over the generated OpenAPI types.
 *
 * `api.generated.ts` is produced from the backend's live spec by
 * `npm run generate:types` and is never hand-edited. Referring to
 * `components['schemas']['ScoreResponse']` everywhere would be unreadable, so the
 * shapes the app actually uses are named here — and because they are aliases, a
 * backend schema change still surfaces as a type error at every use site.
 */
import type { components } from './api.generated';

type Schemas = components['schemas'];

export type PolygonGeometry = Schemas['PolygonGeometry'];
export type Centroid = Schemas['Centroid'];

export type SiteResponse = Schemas['SiteResponse'];
export type SiteCreateRequest = Schemas['SiteCreateRequest'];

export type MaterialResponse = Schemas['MaterialResponse'];
export type MaterialCatalogue = Schemas['MaterialCatalogueResponse'];
export type MaterialSelection = Schemas['MaterialSelection'];
export type BuildingComponent = keyof MaterialSelection;

export type ScoreResponse = Schemas['ScoreResponse'];
export type ScoreRequest = Schemas['ScoreRequest'];
export type ProveResponse = Schemas['ProveResponse'];
export type YearBreakdown = Schemas['YearBreakdown'];
export type ComponentBreakdown = Schemas['ComponentBreakdown'];
export type MaterialRecommendation = Schemas['MaterialRecommendation'];

export type ReportResponse = Schemas['ReportResponse'];
export type ErrorResponse = Schemas['ErrorResponse'];

/** The building components, in the order the backend reports them. */
export const BUILDING_COMPONENTS = ['foundation', 'walls', 'roofing'] as const;

/** The scoring horizon, matching `core/constants.py`. */
export const HORIZON_START_YEAR = 2025;
export const HORIZON_END_YEAR = 2055;
