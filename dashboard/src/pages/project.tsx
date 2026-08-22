/**
 * The public project folder — the page a visitor actually came for.
 *
 * Everything on it is published by the owner: progress, the five stage bars,
 * the timeline, public remarks, and recent geotagged captures. A private
 * project answers 404 from the API, and this page renders that as a friendly
 * not-found rather than an error, because a visitor following a stale link has
 * done nothing wrong and must not learn whether the project exists.
 */

import { Link, useParams } from 'react-router-dom';

import { Card, Coordinates, EmptyState, ErrorState, MapLink, RelativeTime } from '@/components/common';
import { MacroStageLabel, ProgressRing, StageBars, StatusBadge } from '@/components/progress';
import { CaptureStrip } from '@/components/project';
import { TimelineChart } from '@/components/timeline-chart';
import { ApiError } from '@/lib/api';
import { useProject } from '@/lib/queries';

const SEVERITY_STYLES: Record<string, string> = {
  info: 'border-slate-200 bg-white',
  warning: 'border-amber-200 bg-amber-50',
  critical: 'border-rose-200 bg-rose-50',
};

/** The public project page's rooms are the shared `Card`. */
const Section = Card;

export function ProjectPage() {
  const { projectCode = '' } = useParams();
  const query = useProject(projectCode);

  if (query.isPending) {
    return (
      <div className="animate-pulse space-y-4" aria-busy="true" aria-label="Loading project">
        <div className="h-8 w-1/2 rounded bg-slate-200" />
        <div className="h-48 rounded-lg bg-slate-200" />
        <div className="h-64 rounded-lg bg-slate-200" />
      </div>
    );
  }

  if (query.isError) {
    const notFound = query.error instanceof ApiError && query.error.isNotFound;
    return notFound ? (
      <EmptyState
        title="This project is not available"
        description="It may have been removed, or its owner may not have published it."
        action={
          <Link to="/" className="text-sm font-medium text-sky-700 hover:underline">
            Browse public projects
          </Link>
        }
      />
    ) : (
      <ErrorState title="Could not load this project" message={query.error.message} />
    );
  }

  const project = query.data;

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4 border-b border-slate-200 pb-5">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight text-slate-900">{project.name}</h1>
          <p className="mt-1 text-slate-600">
            {project.intended_use ?? 'Construction project'}
            {' · '}
            <span className="font-mono text-xs uppercase tracking-wider text-sky-700">
              {project.project_code}
            </span>
          </p>
          <p className="mt-1 text-sm text-slate-500">{project.location_label}</p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <StatusBadge status={project.status} reason={project.status_reason} />
          <p className="text-xs text-slate-500">{project.status_reason}</p>
        </div>
      </header>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex flex-col gap-6">
          <Section title="Estimated progress">
            <div className="flex flex-wrap items-center gap-8">
              <ProgressRing value={project.progress_pct} />
              <dl className="min-w-[12rem] flex-1 space-y-2 text-sm">
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-500">Current stage</dt>
                  <dd>
                    <MacroStageLabel stage={project.macro_stage} />
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-500">Deadline</dt>
                  <dd className="text-slate-800">
                    {new Date(project.deadline_date).toLocaleDateString(undefined, {
                      dateStyle: 'medium',
                    })}
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-500">Last capture</dt>
                  <dd className="text-slate-800">
                    <RelativeTime value={project.last_capture_at} />
                  </dd>
                </div>
              </dl>
            </div>
          </Section>

          <Section title="Stage breakdown">
            <StageBars stages={project.stages} />
          </Section>

          <Section title="Progress over time">
            <TimelineChart points={project.timeline} />
          </Section>

          <Section title="Recent captures">
            <CaptureStrip captures={project.recent_images} />
          </Section>

          <Section title="Remarks">
            {project.remarks.length === 0 ? (
              <EmptyState title="No public remarks" />
            ) : (
              <ul className="flex flex-col gap-3">
                {project.remarks.map((remark) => (
                  <li
                    key={remark.id}
                    className={`rounded-lg border px-4 py-3 ${SEVERITY_STYLES[remark.severity] ?? SEVERITY_STYLES['info'] ?? ''}`}
                  >
                    <div className="flex items-center justify-between gap-3 text-xs text-slate-500">
                      <span className="font-medium uppercase tracking-wide">
                        {remark.remark_type}
                        {remark.is_system_generated && ' · automatic'}
                      </span>
                      <RelativeTime value={remark.created_at} />
                    </div>
                    <p className="mt-1 text-sm text-slate-800">{remark.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>

        <aside className="flex flex-col gap-6">
          <Section title="Location">
            <div className="space-y-3">
              <p className="text-sm text-slate-700">{project.location_label}</p>
              <Coordinates latitude={project.latitude} longitude={project.longitude} />
              <div className="flex flex-col gap-1.5">
                <MapLink url={project.map_url} />
                <MapLink url={project.osm_url} label="Open in OpenStreetMap" />
              </div>
            </div>
          </Section>

          <Section title="Project handler">
            {project.handler_is_public && project.handler_username ? (
              <Link
                to={`/users/${project.handler_username}`}
                className="text-sm font-medium text-sky-700 hover:underline"
              >
                {project.handler_name ?? project.handler_username}
              </Link>
            ) : (
              // A public project owned by a private-profile user still appears;
              // the owner is plain text, never a link to a page that would only
              // say "this account is private".
              <p className="text-sm text-slate-600">
                {project.handler_username ?? 'Not published'}
              </p>
            )}
          </Section>
        </aside>
      </div>
    </div>
  );
}
