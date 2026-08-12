/**
 * Minimal typed API client.
 *
 * Expanded in Module 11 with TanStack Query hooks per feature. For now it
 * exists to prove the dev proxy reaches FastAPI and that responses are parsed
 * through a validating boundary rather than blindly cast.
 */

export interface HealthResponse {
  status: string;
  app: string;
  version: string;
  environment: string;
}

/** Error carrying the HTTP status, so callers can branch on 401/404/409. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

function isHealthResponse(value: unknown): value is HealthResponse {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return (
    typeof candidate['status'] === 'string' &&
    typeof candidate['app'] === 'string' &&
    typeof candidate['version'] === 'string' &&
    typeof candidate['environment'] === 'string'
  );
}

/** Fetch the backend liveness payload. Throws {@link ApiError} on failure. */
export async function fetchHealth(): Promise<HealthResponse> {
  const response = await fetch('/health');
  if (!response.ok) {
    throw new ApiError(`Health check failed with ${String(response.status)}`, response.status);
  }
  const data: unknown = await response.json();
  if (!isHealthResponse(data)) {
    throw new ApiError('Unexpected health response shape', response.status);
  }
  return data;
}
