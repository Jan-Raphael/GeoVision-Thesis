/**
 * The public shell: header, navigation, footer, and the error boundary.
 *
 * The footer carries the estimate disclaimer on every page. It is the same
 * commitment the PDF report makes (ADR-007): this system publishes an AI
 * estimate from exterior photographs, and a visitor should never have to dig to
 * discover that.
 */

import { Component, type ReactNode } from 'react';
import { Link, NavLink, Outlet, useNavigate } from 'react-router-dom';

import { useSession } from '@/features/auth/session';
import { logout } from '@/lib/auth';

import { ErrorState } from '@/components/common';

const NAV = [
  { to: '/', label: 'Projects', end: true },
  { to: '/search', label: 'Search', end: false },
  { to: '/contact', label: 'Contact', end: false },
];

function Header() {
  const { user, refresh } = useSession();
  const navigate = useNavigate();
  return (
    <header className="sticky top-0 z-20 border-b border-slate-200 bg-white/90 backdrop-blur">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-4 px-4 py-3 sm:px-6">
        <Link
          to="/"
          className="flex items-baseline gap-2 rounded focus:outline-none focus:ring-2 focus:ring-sky-500"
        >
          <span className="text-lg font-semibold tracking-tight text-slate-900">GeoVision</span>
          <span className="hidden text-xs text-slate-500 sm:inline">Construction monitoring</span>
        </Link>

        <nav className="flex items-center gap-1" aria-label="Main">
          {NAV.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              end={item.end}
              className={({ isActive }) =>
                `rounded-md px-3 py-1.5 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-sky-500 ${
                  isActive ? 'bg-slate-100 text-slate-900' : 'text-slate-600 hover:text-slate-900'
                }`
              }
            >
              {item.label}
            </NavLink>
          ))}
          {user ? (
            <>
              <NavLink
                to="/me"
                className={({ isActive }) =>
                  `rounded-md px-3 py-1.5 text-sm font-medium transition focus:outline-none focus:ring-2 focus:ring-sky-500 ${
                    isActive ? 'bg-slate-100 text-slate-900' : 'text-slate-600 hover:text-slate-900'
                  }`
                }
              >
                My projects
              </NavLink>
              <button
                type="button"
                onClick={() => {
                  void logout().then(() => {
                    refresh();
                    navigate('/');
                  });
                }}
                className="ml-1 rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 transition hover:bg-slate-50"
              >
                Sign out
              </button>
            </>
          ) : (
            <Link
              to="/login"
              className="ml-1 rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white transition hover:bg-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500"
            >
              Sign in
            </Link>
          )}
        </nav>
      </div>
    </header>
  );
}

function Footer() {
  return (
    <footer className="mt-16 border-t border-slate-200 bg-white">
      <div className="mx-auto max-w-6xl px-4 py-8 text-sm text-slate-500 sm:px-6">
        <p className="max-w-3xl">
          <strong className="font-medium text-slate-700">Progress figures are estimates.</strong>{' '}
          They are produced by a computer-vision model from exterior photographs, are not a survey
          or a certification, and should not be the sole basis for a payment or scheduling
          decision. Interior work is invisible to the system. The model&rsquo;s own output stops at
          80&nbsp;%; the final stage is recorded only after a physical inspection.
        </p>
        <p className="mt-4 text-xs text-slate-400">
          GeoVision &middot; Smart Construction Monitoring Using AI and Geotagging
        </p>
      </div>
    </footer>
  );
}

interface BoundaryState {
  error: Error | null;
}

/**
 * Catches render-time failures so one broken card cannot blank the site.
 *
 * A class component because React has no hook equivalent — this is the one
 * place the older API is still the only API.
 */
export class ErrorBoundary extends Component<{ children: ReactNode }, BoundaryState> {
  override state: BoundaryState = { error: null };

  static getDerivedStateFromError(error: Error): BoundaryState {
    return { error };
  }

  override render() {
    if (this.state.error) {
      return (
        <div className="mx-auto max-w-2xl px-4 py-16">
          <ErrorState
            title="Something went wrong on this page"
            message="Reloading usually fixes it. If it keeps happening, the site may be updating."
          />
        </div>
      );
    }
    return this.props.children;
  }
}

export function PublicLayout() {
  return (
    <div className="flex min-h-screen flex-col bg-slate-50 text-slate-900">
      <Header />
      <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8 sm:px-6">
        <ErrorBoundary>
          <Outlet />
        </ErrorBoundary>
      </main>
      <Footer />
    </div>
  );
}
