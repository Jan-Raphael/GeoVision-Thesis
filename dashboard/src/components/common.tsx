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

/**
 * The standard panel shell — a bordered card with a small uppercase title,
 * used for every self-contained block of the dashboard (a project's stage
 * breakdown, its device list, a profile's detail panel). Consolidating what
 * used to be three near-identical local `Section`/`Panel` functions means the
 * card styling — corner marks, border, header rule — lives in one place.
 */
export function Card({
  title,
  action,
  framed = false,
  children,
}: {
  title?: string;
  action?: React.ReactNode;
  /** Adds the drafting corner marks — reserve for the page's primary card. */
  framed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <section
      className={`rounded-lg border border-slate-200 bg-white p-5 ${framed ? 'blueprint-frame' : ''}`}
    >
      {title && (
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">
            {title}
          </h2>
          {action}
        </div>
      )}
      <div className={title ? 'mt-4' : ''}>{children}</div>
    </section>
  );
}

/**
 * Small, semi-transparent format guidance under a form field — e.g. the
 * username and password rules on the registration form. Deliberately quiet
 * (`text-slate-500/80`, no border, no icon): it should read as a hint a
 * confident user can ignore, not a warning.
 */
export function FieldHint({ children }: { children: React.ReactNode }) {
  return <p className="field-hint">{children}</p>;
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

/**
 * Placeholder row, sized to the real project row so the layout does not
 * jump once data arrives — matches the single-column list every project
 * listing now uses (feed, "My projects", search, profile).
 */
export function SkeletonCard() {
  return (
    <div className="flex animate-pulse items-center gap-5 rounded-lg border border-slate-200 bg-white p-5">
      <div className="h-16 w-16 shrink-0 rounded-full bg-slate-200" />
      <div className="min-w-0 flex-1 space-y-2.5">
        <div className="h-4 w-2/5 rounded bg-slate-200" />
        <div className="h-3 w-3/5 rounded bg-slate-200" />
        <div className="h-3 w-1/3 rounded bg-slate-200" />
      </div>
      <div className="h-6 w-16 shrink-0 rounded-full bg-slate-200" />
    </div>
  );
}

export function SkeletonGrid({ count = 6 }: { count?: number }) {
  return (
    <div className="flex flex-col gap-3" aria-busy="true" aria-label="Loading projects">
      {Array.from({ length: count }, (_, index) => (
        <SkeletonCard key={index} />
      ))}
    </div>
  );
}
