/**
 * Profile, search, contact, auth placeholders, and 404.
 *
 * The auth pages are deliberately thin here. Module 11 is the anonymous face of
 * the system, and Module 12 owns registration, sign-in, and everything behind
 * them — a half-built login form that posts nowhere would be worse than an
 * honest placeholder.
 */

import { useState } from 'react';
import { Link, useParams, useSearchParams } from 'react-router-dom';

import { EmptyState, ErrorState } from '@/components/common';
import { StatusBadge } from '@/components/progress';
import { PrivateAccountNotice } from '@/components/project';
import { submitContact, type ContactForm, type ProjectStatus } from '@/lib/api';
import { useDebouncedValue } from '@/lib/hooks';
import { useProfile, useSearch } from '@/lib/queries';

// ---------------------------------------------------------------------------
// Public profile
// ---------------------------------------------------------------------------

export function ProfilePage() {
  const { username = '' } = useParams();
  const query = useProfile(username);

  if (query.isPending) {
    return <div className="h-48 animate-pulse rounded-lg bg-slate-200" aria-busy="true" />;
  }
  if (query.isError) {
    return <ErrorState title="Could not load this profile" message={query.error.message} />;
  }

  const profile = query.data;
  if (profile.is_private) return <PrivateAccountNotice username={profile.username} />;

  const projects = profile.projects ?? [];

  return (
    <div className="flex flex-col gap-6">
      <header className="blueprint-frame rounded-lg border border-slate-200 bg-white p-6">
        <h1 className="text-2xl font-semibold tracking-tight text-slate-900">
          {profile.full_name ?? profile.username}
        </h1>
        <p className="mt-1 text-slate-500">@{profile.username}</p>
        <p className="mt-2 text-sm text-slate-700">
          {[profile.professional_role, profile.company].filter(Boolean).join(' · ') ||
            'No role published'}
        </p>
        {profile.bio && <p className="mt-3 max-w-2xl text-sm text-slate-600">{profile.bio}</p>}
      </header>

      <section>
        <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
          Public projects
        </h2>
        {projects.length === 0 ? (
          <EmptyState title="No public projects" />
        ) : (
          <ul className="flex flex-col gap-3">
            {projects.map((project) => (
              <li key={project.project_code}>
                <Link
                  to={`/projects/${project.project_code}`}
                  className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-4 transition hover:border-sky-300 hover:shadow-sm"
                >
                  <span className="min-w-0">
                    <span className="block font-medium text-slate-900">{project.name}</span>
                    <span className="block text-sm text-slate-500">
                      {project.location_label}
                    </span>
                  </span>
                  <span className="flex shrink-0 items-center gap-2">
                    <span className="tabular-nums text-sm text-slate-600">
                      {project.progress_pct.toFixed(0)}%
                    </span>
                    <StatusBadge status={project.status as ProjectStatus} />
                  </span>
                </Link>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Search
// ---------------------------------------------------------------------------

type Tab = 'projects' | 'owners' | 'locations';

export function SearchPage() {
  const [params, setParams] = useSearchParams();
  const term = params.get('q') ?? '';
  const tab = (params.get('tab') ?? 'projects') as Tab;
  const debouncedTerm = useDebouncedValue(term, 300);
  const query = useSearch(debouncedTerm);

  const setParam = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  // The API returns projects and users; the Locations tab is derived from the
  // project matches, which already carry a label and coordinates. See
  // Open-Questions Q13 — there is no separate locations index.
  const locations = (query.data?.projects ?? []).map((project) => ({
    key: project.project_code,
    label: project.location_label,
    name: project.name,
    latitude: project.latitude,
    longitude: project.longitude,
    mapUrl: project.map_url,
  }));

  const counts = {
    projects: query.data?.projects.length ?? 0,
    owners: query.data?.users.length ?? 0,
    locations: locations.length,
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Search</h1>
        <label className="mt-4 block">
          <span className="sr-only">Search owners, projects, and locations</span>
          <input
            type="search"
            autoFocus
            value={term}
            onChange={(event) => {
              setParam('q', event.target.value);
            }}
            placeholder="Search owners, projects, or locations…"
            className="w-full rounded-md border border-slate-300 bg-white px-4 py-2.5 text-sm placeholder:text-slate-400 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
        </label>
      </div>

      {term.trim().length < 2 ? (
        <EmptyState
          title="Type at least two characters"
          description="Search covers published projects, their locations, and public owner profiles."
        />
      ) : (
        <>
          <div className="flex gap-1 border-b border-slate-200" role="tablist">
            {(['projects', 'owners', 'locations'] as Tab[]).map((name) => (
              <button
                key={name}
                type="button"
                role="tab"
                aria-selected={tab === name}
                onClick={() => {
                  setParam('tab', name);
                }}
                className={`-mb-px border-b-2 px-4 py-2 text-sm font-medium capitalize transition focus:outline-none focus:ring-2 focus:ring-sky-500 ${
                  tab === name
                    ? 'border-sky-600 text-sky-700'
                    : 'border-transparent text-slate-500 hover:text-slate-800'
                }`}
              >
                {name} ({counts[name]})
              </button>
            ))}
          </div>

          {query.isPending && <p className="text-sm text-slate-500">Searching…</p>}
          {query.isError && <ErrorState title="Search failed" message={query.error.message} />}

          {query.isSuccess && (
            <div role="tabpanel">
              {tab === 'projects' &&
                (counts.projects === 0 ? (
                  <EmptyState title="No projects match" />
                ) : (
                  <ul className="flex flex-col gap-3">
                    {query.data.projects.map((project) => (
                      <li key={project.project_code}>
                        <Link
                          to={`/projects/${project.project_code}`}
                          className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-4 transition hover:border-sky-300 hover:shadow-sm"
                        >
                          <span className="min-w-0">
                            <span className="block font-medium text-slate-900">
                              {project.name}
                            </span>
                            <span className="block text-sm text-slate-500">
                              {project.location_label}
                            </span>
                          </span>
                          <StatusBadge status={project.status} />
                        </Link>
                      </li>
                    ))}
                  </ul>
                ))}

              {tab === 'owners' &&
                (counts.owners === 0 ? (
                  <EmptyState title="No owners match" />
                ) : (
                  <ul className="flex flex-col gap-3">
                    {query.data.users.map((user) => (
                      <li key={user.username}>
                        <Link
                          to={`/users/${user.username}`}
                          className="block rounded-lg border border-slate-200 bg-white p-4 transition hover:border-sky-300 hover:shadow-sm"
                        >
                          <span className="font-medium text-slate-900">
                            {user.full_name ?? user.username}
                          </span>
                          <span className="ml-2 text-sm text-slate-500">@{user.username}</span>
                          {user.professional_role && (
                            <span className="block text-sm text-slate-500">
                              {user.professional_role}
                              {user.company ? ` · ${user.company}` : ''}
                            </span>
                          )}
                        </Link>
                      </li>
                    ))}
                  </ul>
                ))}

              {tab === 'locations' &&
                (counts.locations === 0 ? (
                  <EmptyState title="No locations match" />
                ) : (
                  <ul className="flex flex-col gap-3">
                    {locations.map((location) => (
                      <li
                        key={location.key}
                        className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white p-4"
                      >
                        <span className="min-w-0">
                          <span className="block font-medium text-slate-900">
                            {location.label}
                          </span>
                          <span className="block text-sm text-slate-500">{location.name}</span>
                        </span>
                        <a
                          href={location.mapUrl}
                          target="_blank"
                          rel="noreferrer noopener"
                          className="shrink-0 text-sm font-medium text-sky-700 hover:underline"
                        >
                          Map ↗
                        </a>
                      </li>
                    ))}
                  </ul>
                ))}
            </div>
          )}
        </>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Contact
// ---------------------------------------------------------------------------

const EMPTY_FORM: ContactForm = { name: '', email: '', subject: '', message: '' };

export function ContactPage() {
  const [form, setForm] = useState<ContactForm>(EMPTY_FORM);
  const [state, setState] = useState<'idle' | 'sending' | 'sent'>('idle');
  const [error, setError] = useState<string | null>(null);

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    setState('sending');
    setError(null);
    submitContact(form).then(
      () => {
        setState('sent');
        setForm(EMPTY_FORM);
      },
      (cause: unknown) => {
        setState('idle');
        setError(cause instanceof Error ? cause.message : 'Could not send your message.');
      },
    );
  };

  if (state === 'sent') {
    return (
      <EmptyState
        title="Thank you — your message has been sent"
        description="We will reply to the email address you provided."
        action={
          <button
            type="button"
            onClick={() => {
              setState('idle');
            }}
            className="text-sm font-medium text-sky-700 hover:underline"
          >
            Send another message
          </button>
        }
      />
    );
  }

  const field = (key: keyof ContactForm, label: string, extra: Record<string, unknown> = {}) => (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      <input
        required
        value={form[key]}
        onChange={(event) => {
          setForm((current) => ({ ...current, [key]: event.target.value }));
        }}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
        {...extra}
      />
    </label>
  );

  return (
    <div className="mx-auto max-w-xl">
      <h1 className="text-2xl font-semibold tracking-tight">Contact us</h1>
      <p className="mt-1 text-slate-600">
        Questions about a monitored project, or about the system itself.
      </p>

      <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
        {field('name', 'Your name', { minLength: 2, maxLength: 120 })}
        {field('email', 'Email', { type: 'email' })}
        {field('subject', 'Subject', { minLength: 3, maxLength: 200 })}
        <label className="block">
          <span className="mb-1 block text-sm font-medium text-slate-700">Message</span>
          <textarea
            required
            minLength={10}
            maxLength={4000}
            rows={6}
            value={form.message}
            onChange={(event) => {
              setForm((current) => ({ ...current, message: event.target.value }));
            }}
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
        </label>

        {error && <ErrorState title="Could not send your message" message={error} />}

        <button
          type="submit"
          disabled={state === 'sending'}
          className="self-start rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white transition hover:bg-slate-700 disabled:opacity-60"
        >
          {state === 'sending' ? 'Sending…' : 'Send message'}
        </button>
      </form>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Auth placeholders and 404
// ---------------------------------------------------------------------------

export function AuthPlaceholderPage({ mode }: { mode: 'login' | 'register' }) {
  return (
    <EmptyState
      title={mode === 'login' ? 'Sign in' : 'Create an account'}
      description="The authenticated dashboard arrives in Module 12. Public projects are browsable without an account."
      action={
        <Link to="/" className="text-sm font-medium text-sky-700 hover:underline">
          Browse public projects
        </Link>
      }
    />
  );
}

export function NotFoundPage() {
  return (
    <EmptyState
      title="Page not found"
      description="The link may be out of date, or the project may not be public."
      action={
        <Link to="/" className="text-sm font-medium text-sky-700 hover:underline">
          Go to the homepage
        </Link>
      }
    />
  );
}
