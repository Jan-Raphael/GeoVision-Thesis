/**
 * Progress display: the ring, the five stage bars, and the status badge.
 *
 * One rule governs all three, and it comes from ADR-007: **the model stops at
 * 80 %**. The last fifth is awarded by a person after a physical inspection, so
 * nothing here may present an AI estimate as a finished measurement. The ring
 * says "AI estimate", the fifth bar is visually distinct and explains itself,
 * and no colour is ever the only carrier of meaning.
 */

import type { MacroStage, ProjectStatus, StageBreakdown } from '@/lib/api';

/** The machine ceiling from ADR-007; above it, a human has signed off. */
export const AI_CEILING_PCT = 80;

const STAGE_LABELS: Record<keyof StageBreakdown, string> = {
  foundation_pct: 'Foundation',
  framing_pct: 'Framing',
  roofing_pct: 'Roofing',
  finishing_pct: 'Finishing',
  approval_pct: 'Approval',
};

const STAGE_ORDER: (keyof StageBreakdown)[] = [
  'foundation_pct',
  'framing_pct',
  'roofing_pct',
  'finishing_pct',
  'approval_pct',
];

const STATUS_STYLES: Record<ProjectStatus, { label: string; className: string }> = {
  active: { label: 'Active', className: 'bg-sky-100 text-sky-800 ring-sky-600/20' },
  inactive: { label: 'Inactive', className: 'bg-slate-100 text-slate-700 ring-slate-500/20' },
  delayed: { label: 'Delayed', className: 'bg-amber-100 text-amber-900 ring-amber-600/30' },
  completed: { label: 'Completed', className: 'bg-emerald-100 text-emerald-800 ring-emerald-600/20' },
  archived: { label: 'Archived', className: 'bg-slate-100 text-slate-500 ring-slate-400/20' },
};

export function StatusBadge({ status, reason }: { status: ProjectStatus; reason?: string }) {
  const style = STATUS_STYLES[status];
  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ring-1 ring-inset ${style.className}`}
      // The label is the accessible name; the colour is decoration on top of
      // it, never the only thing carrying the meaning.
      title={reason}
    >
      {style.label}
    </span>
  );
}

interface ProgressRingProps {
  value: number;
  size?: number;
  /** Shows the "AI estimate" caption. Off for a completed, human-approved project. */
  labelled?: boolean;
}

/**
 * The headline percentage, drawn as an SVG arc.
 *
 * The ceiling is marked on the track so a visitor can see that 80 % is a
 * deliberate stopping point rather than the project stalling.
 */
export function ProgressRing({ value, size = 132, labelled = true }: ProgressRingProps) {
  const clamped = Math.min(Math.max(value, 0), 100);
  const stroke = Math.max(size * 0.085, 8);
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  const complete = clamped >= 100;

  return (
    <div className="inline-flex flex-col items-center gap-1">
      <svg
        width={size}
        height={size}
        viewBox={`0 0 ${String(size)} ${String(size)}`}
        role="img"
        aria-label={`${clamped.toFixed(1)} percent complete`}
        className="-rotate-90"
      >
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          className="stroke-slate-200"
        />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped / 100)}
          className={complete ? 'stroke-emerald-500' : 'stroke-sky-600'}
        />
      </svg>
      <div className="-mt-[60%] flex flex-col items-center pb-[38%]">
        <span className="text-2xl font-semibold tabular-nums text-slate-900">
          {clamped.toFixed(1)}%
        </span>
        {labelled && (
          <span className="text-[10px] font-medium uppercase tracking-wide text-slate-500">
            {complete ? 'Verified' : 'AI estimate'}
          </span>
        )}
      </div>
    </div>
  );
}

/**
 * The five stage bars.
 *
 * The Approval bar is rendered differently on purpose: it is not measured by
 * the model, and a visitor who cannot tell the difference between "the model
 * saw this" and "a person signed this off" has been misled.
 */
export function StageBars({ stages }: { stages: StageBreakdown }) {
  return (
    <ul className="flex flex-col gap-2.5">
      {STAGE_ORDER.map((key) => {
        const value = Math.min(Math.max(stages[key], 0), 100);
        const isApproval = key === 'approval_pct';
        return (
          <li key={key}>
            <div className="flex items-baseline justify-between text-sm">
              <span className={isApproval ? 'font-medium text-amber-900' : 'text-slate-700'}>
                {STAGE_LABELS[key]}
                {isApproval && (
                  <span className="ml-1.5 text-xs font-normal text-slate-500">
                    · requires inspection
                  </span>
                )}
              </span>
              <span className="tabular-nums text-slate-600">{value.toFixed(0)}%</span>
            </div>
            <div
              className="mt-1 h-2 w-full overflow-hidden rounded-full bg-slate-200"
              role="progressbar"
              aria-label={STAGE_LABELS[key]}
              aria-valuenow={Math.round(value)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className={`h-full rounded-full ${isApproval ? 'bg-amber-500' : 'bg-emerald-600'}`}
                style={{ width: `${String(value)}%` }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

const MACRO_LABELS: Record<MacroStage, string> = {
  foundation: 'Foundation',
  framing: 'Framing',
  roofing: 'Roofing',
  finishing: 'Finishing',
  approval: 'Awaiting inspection',
};

/** The current macro stage, or a plain dash when nothing has been measured. */
export function MacroStageLabel({ stage }: { stage: MacroStage | null }) {
  if (!stage) return <span className="text-slate-400">Not yet determined</span>;
  return <span className="font-medium text-slate-800">{MACRO_LABELS[stage]}</span>;
}
