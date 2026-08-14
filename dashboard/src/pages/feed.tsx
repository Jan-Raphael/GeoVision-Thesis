/**
 * The homepage: every public project, filterable.
 *
 * Filters live in the URL rather than in component state, so a filtered view
 * can be linked, bookmarked, and returned to by the back button — which is what
 * a visitor expects from a list of things they might want to show somebody.
 */

import { useSearchParams } from 'react-router-dom';

import { EmptyState, ErrorState, SkeletonGrid } from '@/components/common';
import { ProjectCard } from '@/components/project';
import type { MacroStage, ProjectStatus } from '@/lib/api';
import { useFeed } from '@/lib/queries';

const STATUSES: { value: ProjectStatus | ''; label: string }[] = [
  { value: '', label: 'Any status' },
  { value: 'active', label: 'Active' },
  { value: 'delayed', label: 'Delayed' },
  { value: 'inactive', label: 'Inactive' },
  { value: 'completed', label: 'Completed' },
];

const STAGES: { value: MacroStage | ''; label: string }[] = [
  { value: '', label: 'Any stage' },
  { value: 'foundation', label: 'Foundation' },
  { value: 'framing', label: 'Framing' },
  { value: 'roofing', label: 'Roofing' },
  { value: 'finishing', label: 'Finishing' },
  { value: 'approval', label: 'Awaiting inspection' },
];

export function FeedPage() {
  const [params, setParams] = useSearchParams();
  const q = params.get('q') ?? '';
  const status = (params.get('status') ?? '') as ProjectStatus | '';
  const stage = (params.get('stage') ?? '') as MacroStage | '';

  const feed = useFeed({
    q: q || undefined,
    status: status || undefined,
    stage: stage || undefined,
  });

  const update = (key: string, value: string) => {
    const next = new URLSearchParams(params);
    if (value) next.set(key, value);
    else next.delete(key);
    setParams(next, { replace: true });
  };

  return (
    <div className="flex flex-col gap-6">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">Monitored projects</h1>
        <p className="mt-1 text-slate-600">
          Construction sites published by their owners, with progress estimated from geotagged
          site photographs.
        </p>
      </div>

      <div className="flex flex-wrap items-center gap-3">
        <label className="flex-1 min-w-[14rem]">
          <span className="sr-only">Search projects</span>
          <input
            type="search"
            value={q}
            onChange={(event) => {
              update('q', event.target.value);
            }}
            placeholder="Search by name or location…"
            className="w-full rounded-md border border-slate-300 bg-white px-3 py-2 text-sm placeholder:text-slate-400 focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
        </label>

        <label>
          <span className="sr-only">Filter by status</span>
          <select
            value={status}
            onChange={(event) => {
              update('status', event.target.value);
            }}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            {STATUSES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>

        <label>
          <span className="sr-only">Filter by stage</span>
          <select
            value={stage}
            onChange={(event) => {
              update('stage', event.target.value);
            }}
            className="rounded-md border border-slate-300 bg-white px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          >
            {STAGES.map((option) => (
              <option key={option.value} value={option.value}>
                {option.label}
              </option>
            ))}
          </select>
        </label>
      </div>

      {feed.isPending && <SkeletonGrid />}

      {feed.isError && (
        <ErrorState title="Could not load projects" message={feed.error.message} />
      )}

      {feed.isSuccess && feed.data.items.length === 0 && (
        <EmptyState
          title="No public projects match this view"
          description={
            q || status || stage
              ? 'Try clearing the filters.'
              : 'Projects appear here once an owner publishes one.'
          }
        />
      )}

      {feed.isSuccess && feed.data.items.length > 0 && (
        <div className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3">
          {feed.data.items.map((project) => (
            <ProjectCard key={project.project_code} project={project} />
          ))}
        </div>
      )}
    </div>
  );
}
