/**
 * Session context and the route guard.
 *
 * A single place that knows whether somebody is signed in, so no component has
 * to read `localStorage` and guess. `RequireAuth` renders nothing until the
 * stored token has been checked against `/users/me` — redirecting during that
 * check would bounce a signed-in user to the login page on every hard refresh,
 * which is the classic version of this bug.
 */

import { createContext, useCallback, useContext, useEffect, useMemo, useState } from 'react';
import { Navigate, Outlet, useLocation } from 'react-router-dom';

import { currentUser, onAuthChange, restoreSession, type AuthUser } from '@/lib/auth';

interface SessionValue {
  user: AuthUser | null;
  /** False until the stored token has been checked. */
  ready: boolean;
  refresh: () => void;
}

const SessionContext = createContext<SessionValue>({
  user: null,
  ready: false,
  refresh: () => undefined,
});

export function useSession(): SessionValue {
  return useContext(SessionContext);
}

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [user, setUser] = useState<AuthUser | null>(currentUser());
  const [ready, setReady] = useState(false);

  const refresh = useCallback(() => {
    setUser(currentUser());
  }, []);

  useEffect(() => {
    const stop = onAuthChange(setUser);
    restoreSession()
      .then(setUser)
      .catch(() => {
        setUser(null);
      })
      .finally(() => {
        setReady(true);
      });
    return stop;
  }, []);

  const value = useMemo(() => ({ user, ready, refresh }), [user, ready, refresh]);
  return <SessionContext.Provider value={value}>{children}</SessionContext.Provider>;
}

/** Gate for authenticated routes. */
export function RequireAuth() {
  const { user, ready } = useSession();
  const location = useLocation();

  if (!ready) {
    return (
      <div className="h-48 animate-pulse rounded-xl bg-slate-200" aria-busy="true" aria-label="Loading" />
    );
  }
  if (!user) {
    // `state` carries where they were going, so signing in returns them there
    // rather than dumping everyone on the profile page.
    return <Navigate to="/login" replace state={{ from: location.pathname }} />;
  }
  return <Outlet />;
}
