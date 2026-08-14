/**
 * My Profile (spec B.5) and Create Project (spec B).
 *
 * The create form previews the `project_code` live, because the code is
 * immutable once set — it is embedded in every device name and image filename,
 * so a typo is permanent. Showing it before submission is cheaper than an
 * explanation afterwards.
 */

import { useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';

import { EmptyState, ErrorState, RelativeTime, SkeletonGrid } from '@/components/common';
import { ProgressRing, StatusBadge } from '@/components/progress';
import { useSession } from '@/features/auth/session';
import { useCreateProject, useMyProjects, type CreateProjectInput } from '@/lib/owner';

export function MePage() {
  const { user } = useSession();
  const projects = useMyProjects();

  return (
    <div className="flex flex-col gap-6">
      <header className="rounded-xl border border-slate-200 bg-white p-6">
        <h1 className="text-2xl font-semibold tracking-tight">{user?.full_name ?? 'My profile'}</h1>
        <p className="mt-1 text-slate-500">@{user?.username}</p>
        <p className="mt-2 text-sm text-slate-700">
          {[user?.professional_role, user?.company].filter(Boolean).join(' · ') || 'No role set'}
        </p>
        <p className="mt-2 text-xs text-slate-500">
          Profile is {user?.profile_visibility === 'public' ? 'public' : 'private'}.
        </p>
      </header>

      <div className="flex items-center justify-between">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
          My projects
        </h2>
        <Link
          to="/projects/new"
          className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
        >
          Create project
        </Link>
      </div>

      {projects.isPending && <SkeletonGrid count={3} />}
      {projects.isError && (
        <ErrorState title="Could not load your projects" message={projects.error.message} />
      )}
      {projects.isSuccess &&
        (projects.data.length === 0 ? (
          <EmptyState
            title="No projects yet"
            description="Create one, then pair a camera to start monitoring it."
          />
        ) : (
          <ul className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
            {projects.data.map((project) => (
              <li key={project.id}>
                <Link
                  to={`/projects/${project.id}/manage`}
                  className="flex h-full flex-col rounded-xl border border-slate-200 bg-white p-5 hover:border-slate-300"
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0">
                      <p className="truncate font-semibold text-slate-900">{project.name}</p>
                      <p className="truncate text-sm text-slate-500">{project.project_code}</p>
                    </div>
                    <StatusBadge status={project.status} />
                  </div>
                  <div className="mt-3 flex items-center gap-4">
                    <ProgressRing value={project.progress_pct} size={80} />
                    <div className="min-w-0 text-sm text-slate-600">
                      <p className="truncate">{project.location_label}</p>
                      <p className="mt-1 truncate">
                        <RelativeTime value={project.last_capture_at} />
                      </p>
                      {project.visibility === 'private' && (
                        <p className="mt-1 text-xs text-slate-400">Private</p>
                      )}
                    </div>
                  </div>
                </Link>
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
}

const TODAY = new Date().toISOString().slice(0, 10);

export function CreateProjectPage() {
  const navigate = useNavigate();
  const create = useCreateProject();
  const [form, setForm] = useState<CreateProjectInput>({
    name: '',
    code_initials: '',
    project_number: 0,
    location_label: '',
    latitude: 13.6218,
    longitude: 123.1948,
    start_date: TODAY,
    deadline_date: TODAY,
    visibility: 'private',
  });

  const preview =
    form.code_initials.length >= 2
      ? `${form.code_initials.toUpperCase()}_${String(form.project_number).padStart(2, '0')}`
      : '—';

  const submit = (event: React.FormEvent) => {
    event.preventDefault();
    create.mutate(
      { ...form, code_initials: form.code_initials.toUpperCase() },
      {
        onSuccess: (project) => {
          navigate(`/projects/${project.id}/manage`);
        },
      },
    );
  };

  const set =
    <K extends keyof CreateProjectInput>(key: K) =>
    (value: CreateProjectInput[K]) => {
      setForm((current) => ({ ...current, [key]: value }));
    };

  const text = (label: string, key: 'name' | 'location_label', extra: Record<string, unknown> = {}) => (
    <label className="block">
      <span className="mb-1 block text-sm font-medium text-slate-700">{label}</span>
      <input
        required
        value={form[key]}
        onChange={(event) => {
          set(key)(event.target.value);
        }}
        className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
        {...extra}
      />
    </label>
  );

  return (
    <div className="mx-auto max-w-2xl">
      <h1 className="text-2xl font-semibold tracking-tight">Create a project</h1>

      <form onSubmit={submit} className="mt-6 flex flex-col gap-4">
        {text('Project name', 'name', { minLength: 3, maxLength: 120 })}
        {text('Location', 'location_label')}

        <div className="grid grid-cols-3 gap-3">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Initials</span>
            <input
              required
              value={form.code_initials}
              onChange={(event) => {
                set('code_initials')(event.target.value.replace(/[^a-zA-Z]/g, '').slice(0, 3));
              }}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm uppercase focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
              placeholder="NG"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Number</span>
            <input
              type="number"
              min={0}
              max={99}
              value={form.project_number}
              onChange={(event) => {
                set('project_number')(Number(event.target.value));
              }}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
            />
          </label>
          <div>
            <span className="mb-1 block text-sm font-medium text-slate-700">Project code</span>
            <p className="rounded-md bg-slate-100 px-3 py-2 font-mono text-sm text-slate-800">
              {preview}
            </p>
          </div>
        </div>
        <p className="-mt-2 text-xs text-slate-500">
          The code is permanent — it is embedded in every camera name and image filename.
        </p>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Latitude</span>
            <input
              type="number"
              step="0.000001"
              value={form.latitude}
              onChange={(event) => {
                set('latitude')(Number(event.target.value));
              }}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Longitude</span>
            <input
              type="number"
              step="0.000001"
              value={form.longitude}
              onChange={(event) => {
                set('longitude')(Number(event.target.value));
              }}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
        </div>

        <div className="grid grid-cols-2 gap-3">
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Start date</span>
            <input
              type="date"
              required
              value={form.start_date}
              onChange={(event) => {
                set('start_date')(event.target.value);
              }}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
          <label className="block">
            <span className="mb-1 block text-sm font-medium text-slate-700">Deadline</span>
            <input
              type="date"
              required
              value={form.deadline_date}
              onChange={(event) => {
                set('deadline_date')(event.target.value);
              }}
              className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
            />
          </label>
        </div>

        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={form.visibility === 'public'}
            onChange={(event) => {
              set('visibility')(event.target.checked ? 'public' : 'private');
            }}
            className="h-4 w-4 rounded border-slate-300"
          />
          <span className="text-sm text-slate-700">
            Publish this project so anyone can follow its progress
          </span>
        </label>

        {create.isError && (
          <ErrorState title="Could not create the project" message={create.error.message} />
        )}

        <button
          type="submit"
          disabled={create.isPending}
          className="self-start rounded-md bg-slate-900 px-4 py-2.5 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-60"
        >
          {create.isPending ? 'Creating…' : 'Create project'}
        </button>
      </form>
    </div>
  );
}
