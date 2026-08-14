/**
 * Session storage and the authenticated request path.
 *
 * Tokens live in `localStorage`. That is a deliberate, documented trade-off
 * rather than an oversight: an httpOnly cookie is the stronger choice against
 * XSS, but it needs the API and the dashboard on one origin with CSRF handling,
 * and the ESP32 ingest path already authenticates by HMAC rather than cookie.
 * The mitigation that actually matters here is the **15-minute access token**
 * (ADR-015) — a stolen one expires before it is useful, and the refresh family
 * is revoked on reuse.
 *
 * One behaviour is worth knowing: a 401 triggers **one** transparent refresh and
 * a replay of the original request. Not a loop — if the refresh itself fails the
 * session is cleared and the app returns to signed-out, because retrying a dead
 * session forever is how a login page becomes an infinite spinner.
 */

import { ApiError } from '@/lib/api';

const ACCESS_KEY = 'gv.access';
const REFRESH_KEY = 'gv.refresh';
const API_BASE = '/api/v1';

export interface AuthUser {
  id: string;
  username: string;
  email: string;
  full_name: string;
  professional_role: string;
  profile_visibility: 'public' | 'private';
  company: string | null;
  bio: string | null;
}

export interface Session {
  user: AuthUser;
  access_token: string;
  refresh_token: string;
}

type Listener = (user: AuthUser | null) => void;

const listeners = new Set<Listener>();
let cachedUser: AuthUser | null = null;

/** The current access token, or null when signed out. */
export function accessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY);
}

export function currentUser(): AuthUser | null {
  return cachedUser;
}

/** Subscribe to sign-in and sign-out. Returns an unsubscribe function. */
export function onAuthChange(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function announce(user: AuthUser | null): void {
  cachedUser = user;
  for (const listener of listeners) listener(user);
}

export function storeSession(session: Session): void {
  localStorage.setItem(ACCESS_KEY, session.access_token);
  localStorage.setItem(REFRESH_KEY, session.refresh_token);
  announce(session.user);
}

export function clearSession(): void {
  localStorage.removeItem(ACCESS_KEY);
  localStorage.removeItem(REFRESH_KEY);
  announce(null);
}

async function parse(response: Response): Promise<unknown> {
  return response.json().catch(() => null);
}

function errorFrom(body: unknown, status: number): ApiError {
  if (typeof body === 'object' && body !== null && 'error' in body) {
    const detail = (body as { error: { message?: string; code?: string } }).error;
    return new ApiError(detail.message ?? 'Request failed', status, detail.code);
  }
  return new ApiError(`Request failed with ${String(status)}`, status);
}

/** Exchange the refresh token for a new pair. Returns false if it is dead. */
async function refresh(): Promise<boolean> {
  const token = localStorage.getItem(REFRESH_KEY);
  if (!token) return false;

  const response = await fetch(`${API_BASE}/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: token }),
  }).catch(() => null);

  if (!response?.ok) {
    clearSession();
    return false;
  }
  const body = (await parse(response)) as Session | null;
  if (!body?.access_token) {
    clearSession();
    return false;
  }
  storeSession(body);
  return true;
}

export interface AuthedOptions {
  method?: string;
  body?: unknown;
  /** Multipart payload. Takes precedence over `body`. */
  form?: FormData;
}

/**
 * Perform an authenticated request, refreshing once on a 401.
 *
 * Returns the parsed body, or throws {@link ApiError}. Callers get the server's
 * own message — "This action requires the 'project:approve' permission." reads
 * better than anything this layer could invent, and stays right when the
 * backend's wording changes.
 */
export async function authed<T>(path: string, options: AuthedOptions = {}): Promise<T> {
  const send = async (): Promise<Response> => {
    const token = accessToken();
    const headers: Record<string, string> = { Accept: 'application/json' };
    if (token) headers['Authorization'] = `Bearer ${token}`;
    if (options.body !== undefined) headers['Content-Type'] = 'application/json';

    // Built conditionally rather than passing `body: undefined`:
    // `exactOptionalPropertyTypes` distinguishes an absent property from a
    // present-and-undefined one, and `RequestInit.body` admits only the former.
    const init: RequestInit = { method: options.method ?? 'GET', headers };
    if (options.form) init.body = options.form;
    else if (options.body !== undefined) init.body = JSON.stringify(options.body);

    return fetch(`${API_BASE}${path}`, init);
  };

  let response: Response;
  try {
    response = await send();
  } catch {
    throw new ApiError('Network error — check your connection.', 0);
  }

  if (response.status === 401 && (await refresh())) {
    response = await send();
  }

  const body = await parse(response);
  if (!response.ok) throw errorFrom(body, response.status);
  return body as T;
}

/** Sign in and store the session. */
export async function login(identifier: string, password: string): Promise<AuthUser> {
  const session = await authed<Session>('/auth/login', {
    method: 'POST',
    body: { identifier, password },
  });
  storeSession(session);
  return session.user;
}

export interface RegisterInput {
  username: string;
  email: string;
  password: string;
  full_name: string;
  professional_role: string;
  company?: string;
}

export async function register(input: RegisterInput): Promise<AuthUser> {
  const session = await authed<Session>('/auth/register', { method: 'POST', body: input });
  storeSession(session);
  return session.user;
}

/** Sign out, revoking the refresh family server-side where possible. */
export async function logout(): Promise<void> {
  const token = localStorage.getItem(REFRESH_KEY);
  if (token) {
    // Best effort: a failed revoke must not trap somebody in a session they
    // are trying to leave.
    await authed('/auth/logout', { method: 'POST', body: { refresh_token: token } }).catch(
      () => undefined,
    );
  }
  clearSession();
}

/** Re-establish `currentUser` from a stored token on page load. */
export async function restoreSession(): Promise<AuthUser | null> {
  if (!accessToken()) return null;
  try {
    const user = await authed<AuthUser>('/users/me');
    announce(user);
    return user;
  } catch {
    clearSession();
    return null;
  }
}
