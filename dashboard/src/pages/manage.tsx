/**
 * The owner's project folder — the main workspace (spec B).
 *
 * Two rules govern it.
 *
 * **Every action button is rendered from the server's `permissions` block.**
 * Never from a role inferred in the client. Hiding a button is not security —
 * the API enforces it too — it is honesty: a viewer should not be offered an
 * action that will come back 403.
 *
 * **An AI estimate and an owner confirmation never look alike.** The ring says
 * "AI estimate" until a person has signed off; the Approval bar explains it
 * needs an inspection; and approving is a deliberate, typed, confirmed act
 * recorded against a name (ADR-007). The credibility of the whole system rests
 * on nobody mistaking one for the other.
 */

import { useMemo, useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import {
  Coordinates,
  EmptyState,
  ErrorState,
  MapLink,
  RelativeTime,
} from '@/components/common';
import { MacroStageLabel, ProgressRing, StageBars, StatusBadge } from '@/components/progress';
import { CaptureStrip } from '@/components/project';
import { TimelineChart } from '@/components/timeline-chart';
import { PairingModal } from '@/features/devices/PairingModal';
import { AssetPanel, CaptureLightbox, ReportModal } from '@/features/project/extras';
import { useRealtime } from '@/features/realtime/useRealtime';
import { useApproveProject, useCreateRemark, useFolder } from '@/lib/owner';
import type { RealtimeEvent } from '@/lib/ws';

function Section({
  title,
  action,
  children,
}: {
  title: string;
  action?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section className="rounded-xl border border-slate-200 bg-white p-5">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold uppercase tracking-wide text-slate-500">{title}</h2>
        {action}
      </div>
      <div className="mt-4">{children}</div>
    </section>
  );
}

function ApproveDialog({
  projectId,
  onClose,
}: {
  projectId: string;
  onClose: () => void;
}) {
  const [notes, setNotes] = useState('');
  const approve = useApproveProject(projectId);

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-slate-900/50 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="approve-title"
    >
      <div className="w-full max-w-lg rounded-xl bg-white p-6 shadow-xl">
        <h2 id="approve-title" className="text-lg font-semibold text-slate-900">
          Mark as inspected and complete
        </h2>
        <p className="mt-2 text-sm text-slate-600">
          This finalises the project at <strong>100%</strong>, and is recorded against your name.
          It should follow a physical inspection of the site — the model stops at 80% precisely
          because the last stage is a human judgement.
        </p>
        <label className="mt-4 block">
          <span className="mb-1 block text-sm font-medium text-slate-700">Inspection notes</span>
          <textarea
            required
            rows={4}
            minLength={10}
            value={notes}
            onChange={(event) => {
              setNotes(event.target.value);
            }}
            placeholder="What you inspected, and what you found."
            className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
          />
        </label>

        {approve.isError && (
          <div className="mt-3">
            <ErrorState title="Could not approve" message={approve.error.message} />
          </div>
        )}

        <div className="mt-5 flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50"
          >
            Cancel
          </button>
          <button
            type="button"
            disabled={notes.trim().length < 10 || approve.isPending}
            onClick={() => {
              approve.mutate(notes, { onSuccess: onClose });
            }}
            className="rounded-md bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600 disabled:opacity-50"
          >
            {approve.isPending ? 'Recording…' : 'Confirm completion'}
          </button>
        </div>
      </div>
    </div>
  );
}

export function ManageProjectPage() {
  const { projectId = '' } = useParams();
  const folder = useFolder(projectId);
  const [pairing, setPairing] = useState(false);
  const [approving, setApproving] = useState(false);
  const [pairedName, setPairedName] = useState<string | null>(null);
  const [remark, setRemark] = useState('');
  const [reporting, setReporting] = useState(false);
  const [openCapture, setOpenCapture] = useState<string | null>(null);
  const createRemark = useCreateRemark(projectId);

  const projectIds = useMemo(() => (projectId ? [projectId] : []), [projectId]);
  useRealtime({
    projectIds,
    onEvent: (event: RealtimeEvent) => {
      // The pairing modal confirming itself is the demo moment: nobody on a
      // scaffold should have to press Refresh to find out it worked.
      if (event.type === 'device.paired') {
        const name = event.payload['device_name'];
        setPairedName(typeof name === 'string' ? name : 'Camera');
      }
    },
  });

  if (folder.isPending) {
    return (
      <div className="animate-pulse space-y-4" aria-busy="true" aria-label="Loading project">
        <div className="h-8 w-1/2 rounded bg-slate-200" />
        <div className="h-48 rounded-xl bg-slate-200" />
      </div>
    );
  }
  if (folder.isError) {
    return <ErrorState title="Could not load this project" message={folder.error.message} />;
  }

  const project = folder.data;
  const can = (permission: string): boolean => project.permissions[permission] === true;
  const awaitingInspection = project.approval_state === 'awaiting_inspection';
  const approved = project.approval_state === 'approved';

  return (
    <div className="flex flex-col gap-6">
      <header className="flex flex-wrap items-start justify-between gap-4">
        <div className="min-w-0">
          <h1 className="text-2xl font-semibold tracking-tight">{project.name}</h1>
          <p className="mt-1 text-slate-600">
            {project.intended_use ?? 'Construction project'} · {project.project_code}
          </p>
          <p className="mt-1 text-sm text-slate-500">{project.location_label}</p>
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <StatusBadge status={project.status} reason={project.status_reason} />
          {can('device:manage') && (
            <button
              type="button"
              onClick={() => {
                setPairedName(null);
                setPairing(true);
              }}
              className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white hover:bg-slate-700"
            >
              Pair a camera
            </button>
          )}
          {can('report:generate') && (
            <button
              type="button"
              onClick={() => { setReporting(true); }}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700 hover:bg-slate-50"
            >
              Report
            </button>
          )}
        </div>
      </header>

      <p className="text-sm text-slate-500">{project.status_reason}</p>

      <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_20rem]">
        <div className="flex flex-col gap-6">
          <Section title="Estimated progress">
            <div className="flex flex-wrap items-center gap-8">
              <ProgressRing value={project.progress_pct} labelled={!approved} />
              <dl className="min-w-[12rem] flex-1 space-y-2 text-sm">
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-500">Expected by now</dt>
                  <dd className="tabular-nums text-slate-800">
                    {project.expected_pct.toFixed(1)}%
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-500">Current stage</dt>
                  <dd>
                    <MacroStageLabel stage={project.macro_stage} />
                  </dd>
                </div>
                <div className="flex justify-between gap-4">
                  <dt className="text-slate-500">Days remaining</dt>
                  <dd className="tabular-nums text-slate-800">{project.days_remaining}</dd>
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
            {approved ? (
              <p className="mt-4 rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-900">
                Inspected and confirmed complete.
                {project.inspection_notes && ` — ${project.inspection_notes}`}
              </p>
            ) : awaitingInspection && can('project:approve') ? (
              <button
                type="button"
                onClick={() => {
                  setApproving(true);
                }}
                className="mt-4 rounded-md bg-emerald-700 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-600"
              >
                Mark as inspected &amp; complete
              </button>
            ) : (
              <p className="mt-4 rounded-md bg-slate-50 px-3 py-2 text-xs text-slate-600">
                The final stage is locked until the model reaches 80% and somebody inspects the
                site in person.
              </p>
            )}
          </Section>

          <Section title="Progress over time">
            <TimelineChart points={project.timeline} />
          </Section>

          <Section title="Recent captures">
            <CaptureStrip
              captures={project.recent_images}
              onSelect={(id) => { setOpenCapture(id); }}
            />
          </Section>

          <Section title="Reference files">
            <AssetPanel
              projectId={projectId}
              assets={project.assets}
              canUpload={can('asset:upload')}
            />
          </Section>

          <Section title="Remarks">
            {can('remark:write') && (
              <form
                className="mb-4 flex gap-2"
                onSubmit={(event) => {
                  event.preventDefault();
                  if (!remark.trim()) return;
                  createRemark.mutate(
                    { message: remark, remark_type: 'manual', severity: 'info' },
                    { onSuccess: () => { setRemark(''); } },
                  );
                }}
              >
                <input
                  value={remark}
                  onChange={(event) => {
                    setRemark(event.target.value);
                  }}
                  placeholder="Add a note about this project…"
                  className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-sky-500 focus:outline-none focus:ring-1 focus:ring-sky-500"
                />
                <button
                  type="submit"
                  disabled={createRemark.isPending || !remark.trim()}
                  className="rounded-md bg-slate-900 px-3 py-2 text-sm font-medium text-white disabled:opacity-50"
                >
                  Post
                </button>
              </form>
            )}
            {project.remarks.length === 0 ? (
              <EmptyState title="No remarks yet" />
            ) : (
              <ul className="flex flex-col gap-2">
                {project.remarks.map((entry) => (
                  <li key={entry.id} className="rounded-lg border border-slate-200 px-4 py-3">
                    <div className="flex justify-between gap-3 text-xs text-slate-500">
                      <span className="uppercase tracking-wide">
                        {entry.remark_type}
                        {entry.is_system_generated && ' · automatic'}
                      </span>
                      <RelativeTime value={entry.created_at} />
                    </div>
                    <p className="mt-1 text-sm text-slate-800">{entry.message}</p>
                  </li>
                ))}
              </ul>
            )}
          </Section>
        </div>

        <aside className="flex flex-col gap-6">
          <Section
            title="Cameras"
            action={
              <Link
                to={`/projects/${projectId}/devices`}
                className="text-xs font-medium text-sky-700 hover:underline"
              >
                Manage
              </Link>
            }
          >
            {project.devices.length === 0 ? (
              <EmptyState
                title="No cameras paired"
                description="Pair one to start collecting captures."
              />
            ) : (
              <ul className="flex flex-col gap-2 text-sm">
                {project.devices.map((device) => (
                  <li
                    key={device.id}
                    className="flex items-center justify-between gap-2 rounded-lg border border-slate-200 px-3 py-2"
                  >
                    <span className="min-w-0">
                      <span className="block truncate font-medium">{device.device_name}</span>
                      <span className="block text-xs text-slate-500">
                        <RelativeTime value={device.last_seen_at} />
                      </span>
                    </span>
                    <span
                      className={`shrink-0 rounded-full px-2 py-0.5 text-xs ${
                        device.status === 'online'
                          ? 'bg-emerald-100 text-emerald-800'
                          : 'bg-slate-100 text-slate-600'
                      }`}
                    >
                      {device.status}
                    </span>
                  </li>
                ))}
              </ul>
            )}
          </Section>

          <Section
            title="Collaborators"
            action={
              <Link
                to={`/projects/${projectId}/members`}
                className="text-xs font-medium text-sky-700 hover:underline"
              >
                Manage
              </Link>
            }
          >
            <ul className="flex flex-col gap-1.5 text-sm">
              {project.members.map((member) => (
                <li key={member.id} className="flex justify-between gap-2">
                  <span className="truncate">{member.full_name ?? member.username}</span>
                  <span className="shrink-0 text-xs text-slate-500">
                    {member.membership_role}
                    {member.membership_status !== 'accepted' && ' (pending)'}
                  </span>
                </li>
              ))}
            </ul>
          </Section>

          <Section title="Location">
            <div className="space-y-3">
              <Coordinates latitude={project.latitude} longitude={project.longitude} />
              <MapLink url={project.map_url} />
            </div>
          </Section>
        </aside>
      </div>

      {pairing && (
        <PairingModal
          projectId={projectId}
          pairedDeviceName={pairedName}
          onClose={() => {
            setPairing(false);
            setPairedName(null);
          }}
        />
      )}
      {reporting && (
        <ReportModal projectId={projectId} onClose={() => { setReporting(false); }} />
      )}
      {openCapture && (
        <CaptureLightbox
          projectId={projectId}
          imageId={openCapture}
          onClose={() => { setOpenCapture(null); }}
        />
      )}
      {approving && (
        <ApproveDialog
          projectId={projectId}
          onClose={() => {
            setApproving(false);
          }}
        />
      )}
    </div>
  );
}
