/**
 * The typed boundary between this app and the GeoVision API.
 *
 * Every response passes through a narrowing check before it becomes a typed
 * value. That is deliberate and slightly tedious: `await response.json()` is
 * `any`, and casting it hands the rest of the app types the server never
 * promised. When the contract changes, the failure should be one clear error
 * here rather than `undefined is not a function` three components deep.
 *
 * Only the `/public/*` surface lives here — Module 11 is the anonymous face of
 * the system. Authenticated calls arrive with Module 12.
 */

const API_BASE = '/api/v1';

/** Error carrying the HTTP status, so callers can branch on 404/429/5xx. */
export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly code?: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }

  /** A resource that does not exist, or that this visitor may not know exists. */
  get isNotFound(): boolean {
    return this.status === 404;
  }
}

/** The error envelope every failing endpoint returns. */
interface ErrorEnvelope {
  error: { code: string; message: string };
}

function isErrorEnvelope(value: unknown): value is ErrorEnvelope {
  if (typeof value !== 'object' || value === null) return false;
  const error = (value as Record<string, unknown>)['error'];
  if (typeof error !== 'object' || error === null) return false;
  return typeof (error as Record<string, unknown>)['message'] === 'string';
}

/**
 * Perform a request and narrow the body, or throw {@link ApiError}.
 *
 * The server's error envelope is unwrapped so a caller can show the API's own
 * message — "Project not found." reads better than "Request failed with 404",
 * and it stays correct when the backend's wording changes.
 */
interface RequestOptions {
  method?: string;
  body?: string;
  headers?: Record<string, string>;
}

async function request<T>(
  path: string,
  guard: (value: unknown) => value is T,
  init: RequestOptions = {},
): Promise<T> {
  const { headers, ...rest } = init;
  let response: Response;
  try {
    response = await fetch(`${API_BASE}${path}`, {
      ...rest,
      headers: { Accept: 'application/json', ...headers },
    });
  } catch (cause) {
    // fetch only rejects on a genuine network failure, which is worth
    // distinguishing from an HTTP error the server chose to send.
    throw new ApiError(
      cause instanceof Error ? `Network error: ${cause.message}` : 'Network error',
      0,
    );
  }

  const body: unknown = await response.json().catch(() => null);

  if (!response.ok) {
    if (isErrorEnvelope(body)) {
      throw new ApiError(body.error.message, response.status, body.error.code);
    }
    throw new ApiError(`Request failed with ${String(response.status)}`, response.status);
  }
  if (!guard(body)) {
    throw new ApiError(`Unexpected response shape from ${path}`, response.status);
  }
  return body;
}

// ---------------------------------------------------------------------------
// Shapes — mirroring the response models in `04-API/API-Contract.md`
// ---------------------------------------------------------------------------

export type MacroStage = 'foundation' | 'framing' | 'roofing' | 'finishing' | 'approval';
export type ProjectStatus = 'active' | 'inactive' | 'delayed' | 'completed' | 'archived';

export interface StageBreakdown {
  foundation_pct: number;
  framing_pct: number;
  roofing_pct: number;
  finishing_pct: number;
  approval_pct: number;
}

export interface TimelinePoint {
  window_start: string;
  displayed_pct: number;
  macro_stage: MacroStage;
}

export interface CaptureSummary {
  id: string;
  filename: string;
  captured_at: string;
  latitude: number | null;
  longitude: number | null;
  thumb_url: string | null;
  status: string;
  map_url: string | null;
}

export interface PublicRemark {
  id: string;
  remark_type: string;
  severity: 'info' | 'warning' | 'critical';
  message: string;
  is_system_generated: boolean;
  created_at: string | null;
}

/** One card in the homepage feed. */
export interface FeedProject {
  id: string;
  project_code: string;
  name: string;
  intended_use: string | null;
  location_label: string;
  latitude: number;
  longitude: number;
  progress_pct: number;
  macro_stage: MacroStage | null;
  status: ProjectStatus;
  deadline_date: string;
  last_capture_at: string | null;
  map_url: string;
}

export interface Page<T> {
  items: T[];
  next_cursor: string | null;
  has_more: boolean;
}

/** The anonymous view of one project. */
export interface PublicProject {
  project_code: string;
  name: string;
  intended_use: string | null;
  description: string | null;
  location_label: string;
  latitude: number;
  longitude: number;
  map_url: string;
  osm_url: string;
  start_date: string;
  deadline_date: string;
  status: ProjectStatus;
  status_reason: string;
  progress_pct: number;
  macro_stage: MacroStage | null;
  stages: StageBreakdown;
  handler_username: string | null;
  handler_name: string | null;
  handler_is_public: boolean;
  recent_images: CaptureSummary[];
  remarks: PublicRemark[];
  timeline: TimelinePoint[];
  last_capture_at: string | null;
}

/**
 * A public profile, or the deliberately empty private form.
 *
 * A private account returns `is_private: true` and **nothing else** — not a
 * project count, not a join date. The type mirrors that: every other field is
 * nullable, so a component cannot read one without handling its absence.
 */
export interface PublicProfile {
  username: string;
  is_private: boolean;
  full_name: string | null;
  professional_role: string | null;
  company: string | null;
  bio: string | null;
  /** Public projects this person is involved in. Absent for a private account. */
  projects?: ProfileProject[];
}

export interface ProfileProject {
  project_code: string;
  name: string;
  location_label: string;
  progress_pct: number;
  status: string;
  macro_stage: MacroStage | null;
}

export interface SearchUser {
  username: string;
  full_name: string | null;
  professional_role: string | null;
  company: string | null;
}

/**
 * What `/public/search` actually returns.
 *
 * Note there is **no `locations` array**: the contract describes a Locations
 * tab, but the endpoint returns projects and users only. Each project already
 * carries `location_label`, `latitude`, and `longitude`, so the Locations tab
 * is derived from the project matches client-side rather than pretending the
 * server sent something it did not. See Open-Questions Q13.
 */
export interface SearchResults {
  query: string;
  users: SearchUser[];
  projects: FeedProject[];
}

export interface ContactForm {
  name: string;
  email: string;
  subject: string;
  message: string;
}

// ---------------------------------------------------------------------------
// Guards
// ---------------------------------------------------------------------------

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null;
}

function isFeedProject(value: unknown): value is FeedProject {
  return isRecord(value) && typeof value['project_code'] === 'string' && typeof value['name'] === 'string';
}

function isFeedPage(value: unknown): value is Page<FeedProject> {
  return isRecord(value) && Array.isArray(value['items']) && value['items'].every(isFeedProject);
}

function isPublicProject(value: unknown): value is PublicProject {
  return (
    isRecord(value) &&
    typeof value['project_code'] === 'string' &&
    isRecord(value['stages']) &&
    Array.isArray(value['timeline'])
  );
}

function isPublicProfile(value: unknown): value is PublicProfile {
  return isRecord(value) && typeof value['username'] === 'string' && typeof value['is_private'] === 'boolean';
}

function isSearchResults(value: unknown): value is SearchResults {
  return isRecord(value) && Array.isArray(value['users']) && Array.isArray(value['projects']);
}

function isAcknowledgement(value: unknown): value is { message: string } {
  return isRecord(value) && typeof value['message'] === 'string';
}

// ---------------------------------------------------------------------------
// Calls
// ---------------------------------------------------------------------------

/**
 * Feed filters.
 *
 * Each is `| undefined` explicitly because `exactOptionalPropertyTypes` is on:
 * under that flag an optional property may be *absent* but not *present and
 * undefined*, and callers naturally build this object with `value || undefined`.
 */
export interface FeedFilters {
  q?: string | undefined;
  status?: ProjectStatus | undefined;
  stage?: MacroStage | undefined;
  cursor?: string | undefined;
  limit?: number | undefined;
}

function query(params: Record<string, string | number | undefined>): string {
  const search = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== '') search.set(key, String(value));
  }
  const encoded = search.toString();
  return encoded ? `?${encoded}` : '';
}

/** Homepage feed of public projects. */
export function fetchFeed(filters: FeedFilters = {}): Promise<Page<FeedProject>> {
  return request(`/public/feed${query({ ...filters })}`, isFeedPage);
}

/** One public project by its code. Throws a 404 `ApiError` if it is private. */
export function fetchProject(projectCode: string): Promise<PublicProject> {
  return request(`/public/projects/${encodeURIComponent(projectCode)}`, isPublicProject);
}

/** A user's public profile, or the private-account form. */
export function fetchProfile(username: string): Promise<PublicProfile> {
  return request(`/public/users/${encodeURIComponent(username)}`, isPublicProfile);
}

/** Unified search across owners, projects, and locations. */
export function search(term: string): Promise<SearchResults> {
  return request(`/public/search${query({ q: term })}`, isSearchResults);
}

/** Submit the Contact Us form. */
export function submitContact(form: ContactForm): Promise<{ message: string }> {
  return request('/public/contact', isAcknowledgement, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(form),
  });
}
