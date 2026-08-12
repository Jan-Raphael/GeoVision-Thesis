import { useEffect, useState } from 'react';
import { fetchHealth, type HealthResponse } from '@/lib/api';

/**
 * Module 01 placeholder shell.
 *
 * Its only job is to prove the toolchain end to end: React renders, Tailwind
 * applies, TypeScript type-checks in strict mode, and the Vite dev proxy
 * reaches the FastAPI backend. Real routing arrives in Module 11.
 */
export function App() {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchHealth()
      .then(setHealth)
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : 'Unknown error');
      });
  }, []);

  return (
    <main className="min-h-screen bg-slate-50 text-slate-900">
      <div className="mx-auto flex max-w-2xl flex-col gap-6 px-6 py-16">
        <header>
          <h1 className="text-3xl font-semibold tracking-tight">GeoVision</h1>
          <p className="mt-1 text-slate-600">
            Smart Construction Monitoring Using AI and Geotagging
          </p>
        </header>

        <section className="rounded-lg border border-slate-200 bg-white p-5 shadow-sm">
          <h2 className="text-sm font-medium uppercase tracking-wide text-slate-500">
            Backend connection
          </h2>

          {health && (
            <dl className="mt-3 grid grid-cols-2 gap-y-1 text-sm">
              <dt className="text-slate-500">Status</dt>
              <dd className="font-medium text-emerald-700">{health.status}</dd>
              <dt className="text-slate-500">Version</dt>
              <dd className="font-mono">{health.version}</dd>
              <dt className="text-slate-500">Environment</dt>
              <dd className="font-mono">{health.environment}</dd>
            </dl>
          )}

          {error && (
            <p className="mt-3 text-sm text-amber-700">
              Cannot reach the API ({error}). Start it with{' '}
              <code className="rounded bg-slate-100 px-1 py-0.5 font-mono">.\dev.ps1 api</code>
            </p>
          )}

          {!health && !error && <p className="mt-3 text-sm text-slate-500">Checking…</p>}
        </section>

        <p className="text-sm text-slate-500">
          Module 01 scaffold. The public dashboard is built in Module 11 — see{' '}
          <code className="font-mono">GeoVision-Vault/03-Modules/Build-Order.md</code>.
        </p>
      </div>
    </main>
  );
}
