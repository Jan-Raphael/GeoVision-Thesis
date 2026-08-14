/**
 * Project-shaped components: the feed card, the timeline chart, the capture
 * strip, and the private-account notice.
 */

import { Link } from 'react-router-dom';

import { Coordinates, EmptyState, MapLink, RelativeTime } from '@/components/common';
import { MacroStageLabel, ProgressRing, StatusBadge } from '@/components/progress';
import type { CaptureSummary, FeedProject } from '@/lib/api';

/** One card in the homepage feed. */
export function ProjectCard({ project }: { project: FeedProject }) {
  return (
    <article className="flex flex-col rounded-xl border border-slate-200 bg-white p-5 transition hover:border-slate-300 hover:shadow-sm">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h3 className="truncate text-base font-semibold text-slate-900">
            <Link
              to={`/projects/${project.project_code}`}
              className="rounded focus:outline-none focus:ring-2 focus:ring-sky-500"
            >
              {project.name}
            </Link>
          </h3>
          <p className="mt-0.5 truncate text-sm text-slate-500">
            {project.intended_use ?? 'Construction project'} · {project.project_code}
          </p>
        </div>
        <StatusBadge status={project.status} />
      </div>

      <div className="mt-4 flex items-center gap-5">
        <ProgressRing value={project.progress_pct} size={96} />
        <dl className="min-w-0 flex-1 space-y-1 text-sm">
          <div className="flex gap-2">
            <dt className="text-slate-500">Stage</dt>
            <dd className="truncate">
              <MacroStageLabel stage={project.macro_stage} />
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-slate-500">Location</dt>
            <dd className="truncate text-slate-700">{project.location_label}</dd>
          </div>
          <div className="flex gap-2">
            <dt className="text-slate-500">Last capture</dt>
            <dd className="truncate text-slate-700">
              <RelativeTime value={project.last_capture_at} />
            </dd>
          </div>
        </dl>
      </div>

      <div className="mt-4 flex items-center justify-between border-t border-slate-100 pt-3">
        <Coordinates latitude={project.latitude} longitude={project.longitude} />
        <MapLink url={project.map_url} label="Map" />
      </div>
    </article>
  );
}

/** Recent captures, each with its geotag and timestamp. */
export function CaptureStrip({ captures }: { captures: CaptureSummary[] }) {
  if (captures.length === 0) {
    return (
      <EmptyState
        title="No captures published yet"
        description="Photographs appear here once a paired camera has uploaded them."
      />
    );
  }

  return (
    <ul className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {captures.map((capture) => (
        <li
          key={capture.id}
          className="overflow-hidden rounded-lg border border-slate-200 bg-white"
        >
          <div className="aspect-[4/3] w-full bg-slate-100">
            {capture.thumb_url ? (
              <img
                src={capture.thumb_url}
                // Derived from what the capture actually is, so the alt text is
                // informative rather than a repeated filename.
                alt={`Site capture taken ${new Date(capture.captured_at).toLocaleDateString()}`}
                loading="lazy"
                className="h-full w-full object-cover"
              />
            ) : (
              <div className="flex h-full w-full items-center justify-center text-xs text-slate-400">
                No preview
              </div>
            )}
          </div>
          <div className="space-y-1 p-2.5 text-xs">
            <p className="text-slate-600">
              <RelativeTime value={capture.captured_at} />
            </p>
            {capture.latitude !== null && capture.longitude !== null ? (
              <Coordinates latitude={capture.latitude} longitude={capture.longitude} />
            ) : (
              <p className="text-slate-400">No GPS fix</p>
            )}
            {capture.map_url && <MapLink url={capture.map_url} label="Map" />}
          </div>
        </li>
      ))}
    </ul>
  );
}

/**
 * What a private profile shows.
 *
 * The username and this sentence, and nothing else — no project count, no
 * avatar, no join date. Anything more would leak a fact the account holder
 * chose to withhold.
 */
export function PrivateAccountNotice({ username }: { username: string }) {
  return (
    <div className="rounded-lg border border-slate-200 bg-white px-6 py-12 text-center">
      <p className="text-lg font-medium text-slate-900">@{username}</p>
      <p className="mt-2 text-sm text-slate-500">This account is private.</p>
    </div>
  );
}
