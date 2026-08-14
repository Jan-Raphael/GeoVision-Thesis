/**
 * The small shared pieces: timestamps, coordinates, empty states, skeletons.
 *
 * Empty and loading states live here rather than being improvised per page
 * because they are most of the perceived quality of a dashboard, and because a
 * site with no captures yet is a normal state of this system rather than an
 * error to apologise for.
 */

import { formatDistanceToNowStrict, parseISO } from 'date-fns';
import { useState } from 'react';

/**
 * A timestamp shown as both relative age and absolute value.
 *
 * Relative first, because staleness is the most decision-relevant fact about a
 * construction capture — "3 weeks ago" answers the visitor's real question in a
 * way "14 Aug 2026, 07:00" does not. The absolute value stays in the tooltip
 * and in the accessible name, since a relative age alone cannot be cited.
 */
export function RelativeTime({ value, prefix }: { value: string | null; prefix?: string }) {
  if (!value) return <span className="text-slate-400">no captures yet</span>;

  const parsed = parseISO(value);
  if (Number.isNaN(parsed.getTime())) return <span className="text-slate-400">unknown</span>;

  const absolute = parsed.toLocaleString(undefined, {
    dateStyle: 'medium',
    timeStyle: 'short',
  });
  return (
    <time dateTime={value} title={absolute} className="whitespace-nowrap">
      {prefix ? `${prefix} ` : ''}
      {formatDistanceToNowStrict(parsed, { addSuffix: true })}
    </time>
  );
}

/** Coordinates to six decimals, with a copy button. */
export function Coordinates({ latitude, longitude }: { latitude: number; longitude: number }) {
  const [copied, setCopied] = useState(false);
  const text = `${latitude.toFixed(6)}, ${longitude.toFixed(6)}`;

  const copy = () => {
    // Guarded rather than optional-chained: the DOM types promise
    // `navigator.clipboard` exists, but it is absent over plain HTTP and in
    // jsdom, so the check is about reality rather than about the type.
    if (typeof navigator === 'undefined' || !('clipboard' in navigator)) return;
    void navigator.clipboard.writeText(text).then(
      () => {
        setCopied(true);
        setTimeout(() => {
          setCopied(false);
        }, 1500);
      },
      () => {
        // A denied clipboard permission is not worth an error state; the
        // coordinates are on screen and can be selected by hand.
      },
    );
  };

  return (
    <span className="inline-flex items-center gap-1.5">
      <span className="font-mono text-xs tabular-nums text-slate-600">{text}</span>
      <button
        type="button"
        onClick={copy}
        className="rounded px-1.5 py-0.5 text-xs text-slate-500 hover:bg-slate-100 hover:text-slate-700 focus:outline-none focus:ring-2 focus:ring-sky-500"
        aria-label={`Copy coordinates ${text}`}
      >
        {copied ? 'Copied' : 'Copy'}
      </button>
    </span>
  );
}

/** An external map link. Opens in a new tab, and says so to a screen reader. */
export function MapLink({ url, label = 'Open in Maps' }: { url: string; label?: string }) {
  return (
    <a
      href={url}
      target="_blank"
      rel="noreferrer noopener"
      className="inline-flex items-center gap-1 text-sm font-medium text-sky-700 underline-offset-2 hover:underline"
    >
      {label}
      <span aria-hidden="true">↗</span>
      <span className="sr-only">(opens in a new tab)</span>
    </a>
  );
}

interface EmptyStateProps {
  title: string;
  description?: string;
  action?: React.ReactNode;
}

/** What a surface shows when there is genuinely nothing to show. */
export function EmptyState({ title, description, action }: EmptyStateProps) {
  return (
    <div className="rounded-lg border border-dashed border-slate-300 bg-white/60 px-6 py-10 text-center">
      <p className="text-sm font-medium text-slate-800">{title}</p>
      {description && <p className="mx-auto mt-1 max-w-md text-sm text-slate-500">{description}</p>}
      {action && <div className="mt-4">{action}</div>}
    </div>
  );
}

/** A failure a visitor can act on, rather than a stack trace. */
export function ErrorState({ title, message }: { title: string; message?: string }) {
  return (
    <div
      role="alert"
      className="rounded-lg border border-rose-200 bg-rose-50 px-6 py-8 text-center"
    >
      <p className="text-sm font-medium text-rose-900">{title}</p>
      {message && <p className="mx-auto mt-1 max-w-md text-sm text-rose-700">{message}</p>}
    </div>
  );
}

/** Placeholder card, sized to the real one so the layout does not jump. */
export function SkeletonCard() {
  return (
    <div className="animate-pulse rounded-xl border border-slate-200 bg-white p-5">
      <div className="h-4 w-2/3 rounded bg-slate-200" />
      <div className="mt-2 h-3 w-1/3 rounded bg-slate-200" />
      <div className="mt-5 h-20 w-20 rounded-full bg-slate-200" />
      <div className="mt-5 h-3 w-1/2 rounded bg-slate-200" />
    </div>
  );
}

export function SkeletonGrid({ count = 6 }: { count?: number }) {
  return (
    <div
      className="grid gap-5 sm:grid-cols-2 lg:grid-cols-3"
      aria-busy="true"
      aria-label="Loading projects"
    >
      {Array.from({ length: count }, (_, index) => (
        <SkeletonCard key={index} />
      ))}
    </div>
  );
}
