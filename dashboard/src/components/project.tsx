/**
 * Project-shaped components: the feed row, the timeline chart, the capture
 * strip, and the private-account notice.
 */

import { memo } from 'react';
import { Link } from 'react-router-dom';

import { Coordinates, EmptyState, MapLink, RelativeTime } from '@/components/common';
import { MacroStageLabel, ProgressRing, StatusBadge } from '@/components/progress';
import type { CaptureSummary, FeedProject } from '@/lib/api';

/**
 * One row in the homepage feed.
 *
 * A single full-width row rather than a grid tile, so a long project name, a
 * long location string, or a long intended-use description has room to wrap
 * instead of being cut off with an ellipsis — the whole point of a project
 * folder is to be legible at a glance, and a truncated address is not.
 * `memo`'d because a feed can run to dozens of these and only the rows whose
 * underlying data actually changed need to re-render.
 */
export const ProjectCard = memo(function ProjectCard({ project }: { project: FeedProject }) {
  return (
    <article className="cv-auto group relative flex flex-col gap-4 rounded-lg border border-slate-200 bg-white p-5 transition hover:border-sky-300 hover:shadow-md sm:flex-row sm:items-start">
      {/* The drafting-blue rail: a quiet, always-present brand mark on every row. */}
      <span
        aria-hidden="true"
        className="absolute inset-y-0 left-0 w-1 rounded-l-lg bg-sky-600/0 transition group-hover:bg-sky-600/70"
      />

      <div className="flex shrink-0 items-center gap-4 sm:flex-col sm:items-start sm:gap-2">
        <ProgressRing value={project.progress_pct} size={84} />
      </div>

      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-start justify-between gap-3">
          <div className="min-w-0">
            <h3 className="text-base font-semibold leading-snug text-slate-900">
              <Link
                to={`/projects/${project.project_code}`}
                className="rounded hover:text-sky-700 focus:outline-none focus:ring-2 focus:ring-sky-500"
              >
                {project.name}
              </Link>
            </h3>
            <p className="mt-0.5 text-sm text-slate-500">
              {project.intended_use ?? 'Construction project'}
              {' · '}
              <span className="font-mono text-xs uppercase tracking-wider text-slate-400">
                {project.project_code}
              </span>
            </p>
          </div>
          <StatusBadge status={project.status} />
        </div>

        <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
          <div className="flex gap-2">
            <dt className="w-28 shrink-0 text-slate-500">Stage</dt>
            <dd>
              <MacroStageLabel stage={project.macro_stage} />
            </dd>
          </div>
          <div className="flex gap-2">
            <dt className="w-28 shrink-0 text-slate-500">Last capture</dt>
            <dd className="text-slate-700">
              <RelativeTime value={project.last_capture_at} />
            </dd>
          </div>
          <div className="flex gap-2 sm:col-span-2">
            <dt className="w-28 shrink-0 text-slate-500">Location</dt>
            <dd className="text-slate-700">{project.location_label}</dd>
          </div>
        </dl>

        <div className="mt-3 flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 pt-3">
          <Coordinates latitude={project.latitude} longitude={project.longitude} />
          <MapLink url={project.map_url} label="Map" />
        </div>
      </div>
    </article>
  );
});

/**
 * Recent captures, each with its geotag and timestamp.
 *
 * `onSelect` is optional: the public project page shows captures as a plain
 * strip, while the owner's folder makes each one open the lightbox. Passing the
 * handler rather than branching on a `mode` flag keeps the public surface
 * incapable of opening a view it should not have.
 */
export function CaptureStrip({
  captures,
  onSelect,
}: {
  captures: CaptureSummary[];
  onSelect?: (imageId: string) => void;
}) {
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
          <div
            className={`aspect-[4/3] w-full bg-slate-100 ${onSelect ? 'cursor-zoom-in' : ''}`}
            onClick={onSelect ? () => { onSelect(capture.id); } : undefined}
          >
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
