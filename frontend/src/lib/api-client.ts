/**
 * The single typed API client. Every request in the app goes through here.
 *
 * No component calls `fetch` directly — that rule is what stops error handling,
 * correlation IDs and base URLs from being reimplemented slightly differently in
 * a dozen places.
 *
 * Backend errors all share one envelope, so they are decoded once here and thrown
 * as `ApiError`, which carries the machine-readable code the UI branches on.
 */
import type {
  MaterialCatalogue,
  MaterialSelection,
  ProveResponse,
  ReportResponse,
  ScoreResponse,
  SiteCreateRequest,
  SiteResponse,
} from '@/types/api';

/** Requests go to the same origin; Vite proxies `/api` to the backend in dev. */
const API_BASE = '/api';

/** A structured failure from the backend, or a transport failure. */
export class ApiError extends Error {
  readonly code: string;
  readonly status: number;
  readonly details: Record<string, unknown> | undefined;
  readonly requestId: string | undefined;

  constructor(
    message: string,
    options: {
      code: string;
      status: number;
      details?: Record<string, unknown> | undefined;
      requestId?: string | undefined;
    }
  ) {
    super(message);
    this.name = 'ApiError';
    this.code = options.code;
    this.status = options.status;
    this.details = options.details;
    this.requestId = options.requestId;
  }

  /** Whether the failure is a missing third-party credential rather than a bug. */
  get isUnconfigured(): boolean {
    return this.code === 'EXTERNAL_SERVICE_UNCONFIGURED';
  }
}

function isErrorEnvelope(
  value: unknown
): value is { error: { code: string; message: string; details?: Record<string, unknown>; request_id?: string } } {
  return (
    typeof value === 'object' &&
    value !== null &&
    // `'error' in value` already narrows the type, so no assertion is needed here.
    'error' in value &&
    typeof value.error === 'object'
  );
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // Built via Headers rather than object spread: HeadersInit may be an array or a
  // Headers instance, and spreading either into an object yields index keys.
  const headers = new Headers(init?.headers);
  headers.set('Content-Type', 'application/json');

  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, { ...init, headers });
  } catch (cause) {
    // A network-level failure has no envelope to decode, so it is given one here
    // rather than surfacing as a bare TypeError in a component.
    throw new ApiError('Could not reach the server. Is the backend running?', {
      code: 'NETWORK_ERROR',
      status: 0,
      details: { cause: cause instanceof Error ? cause.message : String(cause) },
    });
  }

  const requestId = response.headers.get('X-Request-ID') ?? undefined;

  const body: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    if (isErrorEnvelope(body)) {
      throw new ApiError(body.error.message, {
        code: body.error.code,
        status: response.status,
        details: body.error.details,
        requestId: body.error.request_id ?? requestId,
      });
    }
    throw new ApiError(`Request failed with status ${String(response.status)}.`, {
      code: 'UNKNOWN_ERROR',
      status: response.status,
      requestId,
    });
  }

  return body as T;
}

export const apiClient = {
  /** Store a drawn site boundary. Area is computed server-side from the polygon. */
  createSite(payload: SiteCreateRequest): Promise<SiteResponse> {
    return request<SiteResponse>('/sites', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
  },

  /** Fetch the material catalogue, grouped by building component. */
  getMaterials(): Promise<MaterialCatalogue> {
    return request<MaterialCatalogue>('/materials');
  },

  /** Compute the Climate Lien Score for a site and material selection. */
  createScore(siteId: string, materials: MaterialSelection): Promise<ScoreResponse> {
    return request<ScoreResponse>('/score', {
      method: 'POST',
      body: JSON.stringify({ site_id: siteId, materials }),
    });
  },

  /** Score, recommend better materials, and re-score with them applied. */
  prove(siteId: string, materials: MaterialSelection): Promise<ProveResponse> {
    return request<ProveResponse>('/score/prove', {
      method: 'POST',
      body: JSON.stringify({ site_id: siteId, materials }),
    });
  },

  /** Generate a plain-English report for a computed score. */
  createReport(scoreId: string): Promise<ReportResponse> {
    return request<ReportResponse>('/reports', {
      method: 'POST',
      body: JSON.stringify({ score_id: scoreId }),
    });
  },
};
