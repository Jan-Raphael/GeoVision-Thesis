/**
 * The remaining owner screens: devices, collaborators, invitations, profile.
 *
 * All four render their actions from the folder's `permissions` block, the same
 * as the workspace. A viewer opening the members page sees the roster and no
 * buttons — the API would refuse them anyway, and offering them is a lie.
 */

import { useState } from 'react';
import { Link, useParams } from 'react-router-dom';

import { Card, EmptyState, ErrorState, RelativeTime } from '@/components/common';
import { useSession } from '@/features/auth/session';
import {
  useChangeMemberRole,
  useFolder,
  useInvitations,
  useInviteMember,
  useRemoveMember,
  useRespondToInvitation,
  useSetProfileVisibility,
  useUnpairDevice,
  useUpdateDevice,
  useUpdateProfile,
  type Device,
} from '@/lib/owner';

const ROLES = ['viewer', 'employee', 'collaborator', 'editor', 'engineer', 'manager'];

/** This page's rooms are the shared `Card`, under the local name they were introduced with. */
const Panel = Card;

function BackToProject({ projectId }: { projectId: string }) {
  return (
    <Link
      to={`/projects/${projectId}/manage`}
      className="text-sm font-medium text-sky-700 hover:underline"
    >
      ← Back to the project
    </Link>
  );
}

// ---------------------------------------------------------------------------
// Devices
// ---------------------------------------------------------------------------

const STATUS_STYLE: Record<string, string> = {
  online: 'bg-emerald-100 text-emerald-800',
  offline: 'bg-amber-100 text-amber-900',
  paired: 'bg-sky-100 text-sky-800',
  revoked: 'bg-slate-100 text-slate-500',
  unpaired: 'bg-slate-100 text-slate-500',
};

function DeviceRow({
  device,
  projectId,
  canManage,
}: {
  device: Device;
  projectId: string;
  canManage: boolean;
}) {
  const update = useUpdateDevice(projectId);
  const unpair = useUnpairDevice(projectId);
  const [confirming, setConfirming] = useState(false);

  return (
    <li className="rounded-lg border border-slate-200 p-4">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0">
          <p className="font-medium text-slate-900">{device.device_name}</p>
          <p className="text-sm text-slate-500">
            {device.face.replace('_', ' ')} · last seen <RelativeTime value={device.last_seen_at} />
          </p>
          <p className="mt-1 text-xs text-slate-500">
            {device.last_battery_mv ? `${String(device.last_battery_mv)} mV` : 'battery unknown'}
            {device.last_rssi_dbm !== null && ` · ${String(device.last_rssi_dbm)} dBm`}
          </p>
        </div>
        <span
          className={`shrink-0 rounded-full px-2.5 py-0.5 text-xs font-medium ${
            STATUS_STYLE[device.status] ?? STATUS_STYLE['unpaired'] ?? ''
          }`}
        >
          {device.status}
        </span>
      </div>

      {canManage && device.status !== 'revoked' && (
        <div className="mt-3 flex flex-wrap items-end gap-3 border-t border-slate-100 pt-3">
          <label className="text-sm">
            <span className="mb-1 block text-xs text-slate-500">
              Weight in the multi-camera average
            </span>
            <input
              type="number"
              min={0}
              max={1}
              step={0.1}
              defaultValue={device.weight}
              onBlur={(event) => {
                const weight = Number(event.target.value);
                if (weight !== device.weight) {
                  update.mutate({ deviceId: device.id, settings: { weight } });
                }
              }}
              className="w-24 rounded-md border border-slate-300 px-2 py-1 text-sm"
            />
          </label>

          {confirming ? (
            <span className="flex items-center gap-2 text-sm">
              <span className="text-slate-600">Unpair? Its images are kept.</span>
              <button
                type="button"
                onClick={() => {
                  unpair.mutate(device.id, { onSuccess: () => { setConfirming(false); } });
                }}
                className="rounded-md bg-rose-700 px-3 py-1.5 text-xs font-medium text-white"
              >
                Confirm
              </button>
              <button
                type="button"
                onClick={() => { setConfirming(false); }}
                className="text-xs text-slate-500 hover:underline"
              >
                Cancel
              </button>
            </span>
          ) : (
            <button
              type="button"
              onClick={() => { setConfirming(true); }}
              className="rounded-md border border-slate-300 px-3 py-1.5 text-xs font-medium text-slate-700 hover:bg-slate-50"
            >
              Unpair
            </button>
          )}
        </div>
      )}
    </li>
  );
}

export function DevicesPage() {
  const { projectId = '' } = useParams();
  const folder = useFolder(projectId);

  if (folder.isPending) return <div className="h-48 animate-pulse rounded-lg bg-slate-200" />;
  if (folder.isError) {
    return <ErrorState title="Could not load devices" message={folder.error.message} />;
  }

  const canManage = folder.data.permissions['device:manage'] === true;

  return (
    <div className="flex flex-col gap-4">
      <BackToProject projectId={projectId} />
      <h1 className="text-2xl font-semibold tracking-tight">Cameras</h1>
      <Panel title={`${String(folder.data.devices.length)} paired`}>
        {folder.data.devices.length === 0 ? (
          <EmptyState
            title="No cameras paired"
            description="Use “Pair a camera” on the project page to add one."
          />
        ) : (
          <ul className="flex flex-col gap-3">
            {folder.data.devices.map((device) => (
              <DeviceRow
                key={device.id}
                device={device}
                projectId={projectId}
                canManage={canManage}
              />
            ))}
          </ul>
        )}
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Collaborators
// ---------------------------------------------------------------------------

export function MembersPage() {
  const { projectId = '' } = useParams();
  const folder = useFolder(projectId);
  const invite = useInviteMember(projectId);
  const changeRole = useChangeMemberRole(projectId);
  const remove = useRemoveMember(projectId);
  const [identifier, setIdentifier] = useState('');
  const [role, setRole] = useState('viewer');

  if (folder.isPending) return <div className="h-48 animate-pulse rounded-lg bg-slate-200" />;
  if (folder.isError) {
    return <ErrorState title="Could not load collaborators" message={folder.error.message} />;
  }

  const canManage = folder.data.permissions['member:manage'] === true;

  return (
    <div className="flex flex-col gap-4">
      <BackToProject projectId={projectId} />
      <h1 className="text-2xl font-semibold tracking-tight">Collaborators</h1>

      {canManage && (
        <Panel title="Invite someone">
          <form
            className="flex flex-wrap items-end gap-3"
            onSubmit={(event) => {
              event.preventDefault();
              if (!identifier.trim()) return;
              invite.mutate(
                { identifier: identifier.trim(), membership_role: role },
                { onSuccess: () => { setIdentifier(''); } },
              );
            }}
          >
            <label className="flex-1 min-w-[14rem]">
              <span className="mb-1 block text-sm font-medium text-slate-700">
                Username or email
              </span>
              <input
                value={identifier}
                onChange={(event) => { setIdentifier(event.target.value); }}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
              />
            </label>
            <label>
              <span className="mb-1 block text-sm font-medium text-slate-700">Role</span>
              <select
                value={role}
                onChange={(event) => { setRole(event.target.value); }}
                className="rounded-md border border-slate-300 px-3 py-2 text-sm capitalize"
              >
                {ROLES.map((name) => (
                  <option key={name} value={name}>
                    {name}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              disabled={invite.isPending || !identifier.trim()}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-50"
            >
              {invite.isPending ? 'Inviting…' : 'Send invite'}
            </button>
          </form>
          {invite.isError && (
            <div className="mt-3">
              <ErrorState title="Could not invite" message={invite.error.message} />
            </div>
          )}
        </Panel>
      )}

      <Panel title={`${String(folder.data.members.length)} people`}>
        <ul className="flex flex-col gap-2">
          {folder.data.members.map((member) => (
            <li
              key={member.id}
              className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 px-4 py-3"
            >
              <span className="min-w-0">
                <span className="block truncate font-medium text-slate-900">
                  {member.full_name ?? member.username}
                </span>
                <span className="block truncate text-sm text-slate-500">
                  @{member.username}
                  {member.membership_status !== 'accepted' && ` · ${member.membership_status}`}
                </span>
              </span>

              {canManage && member.membership_role !== 'owner' ? (
                <span className="flex items-center gap-2">
                  <select
                    value={member.membership_role}
                    onChange={(event) => {
                      changeRole.mutate({ memberId: member.id, role: event.target.value });
                    }}
                    className="rounded-md border border-slate-300 px-2 py-1 text-sm capitalize"
                  >
                    {ROLES.map((name) => (
                      <option key={name} value={name}>
                        {name}
                      </option>
                    ))}
                  </select>
                  <button
                    type="button"
                    onClick={() => { remove.mutate(member.id); }}
                    className="text-xs font-medium text-rose-700 hover:underline"
                  >
                    Remove
                  </button>
                </span>
              ) : (
                <span className="text-sm capitalize text-slate-500">{member.membership_role}</span>
              )}
            </li>
          ))}
        </ul>
      </Panel>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Invitations
// ---------------------------------------------------------------------------

export function InvitationsPage() {
  const invitations = useInvitations();
  const respond = useRespondToInvitation();

  return (
    <div className="flex flex-col gap-4">
      <h1 className="text-2xl font-semibold tracking-tight">Invitations</h1>

      {invitations.isPending && <div className="h-32 animate-pulse rounded-lg bg-slate-200" />}
      {invitations.isError && (
        <ErrorState title="Could not load invitations" message={invitations.error.message} />
      )}
      {invitations.isSuccess &&
        (invitations.data.length === 0 ? (
          <EmptyState
            title="No pending invitations"
            description="When somebody invites you to a project, it appears here."
          />
        ) : (
          <ul className="flex flex-col gap-3">
            {invitations.data.map((invitation) => (
              <li
                key={invitation.id}
                className="flex flex-wrap items-center justify-between gap-3 rounded-lg border border-slate-200 bg-white px-4 py-3"
              >
                <span className="min-w-0">
                  <span className="block truncate font-medium">
                    {invitation.project_name ?? invitation.project_code ?? 'A project'}
                  </span>
                  <span className="block text-sm capitalize text-slate-500">
                    as {invitation.membership_role} ·{' '}
                    <RelativeTime value={invitation.invited_at} />
                  </span>
                </span>
                <span className="flex gap-2">
                  <button
                    type="button"
                    disabled={respond.isPending}
                    onClick={() => {
                      respond.mutate({ memberId: invitation.id, accept: true });
                    }}
                    className="rounded-md bg-slate-900 px-3 py-1.5 text-sm font-medium text-white disabled:opacity-50"
                  >
                    Accept
                  </button>
                  <button
                    type="button"
                    disabled={respond.isPending}
                    onClick={() => {
                      respond.mutate({ memberId: invitation.id, accept: false });
                    }}
                    className="rounded-md border border-slate-300 px-3 py-1.5 text-sm font-medium text-slate-700"
                  >
                    Decline
                  </button>
                </span>
              </li>
            ))}
          </ul>
        ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Profile editing
// ---------------------------------------------------------------------------

export function ProfileEditPage() {
  const { user, refresh } = useSession();
  const update = useUpdateProfile();
  const setVisibility = useSetProfileVisibility();
  const [form, setForm] = useState({
    full_name: user?.full_name ?? '',
    company: user?.company ?? '',
    bio: user?.bio ?? '',
  });
  const [saved, setSaved] = useState(false);
  const isPublic = user?.profile_visibility === 'public';

  return (
    <div className="mx-auto flex max-w-xl flex-col gap-4">
      <Link to="/me" className="text-sm font-medium text-sky-700 hover:underline">
        ← Back to my profile
      </Link>
      <h1 className="text-2xl font-semibold tracking-tight">Edit profile</h1>

      <Panel title="Details">
        <form
          className="flex flex-col gap-4"
          onSubmit={(event) => {
            event.preventDefault();
            setSaved(false);
            update.mutate(form, {
              onSuccess: () => {
                setSaved(true);
                refresh();
              },
            });
          }}
        >
          {(['full_name', 'company', 'bio'] as const).map((key) => (
            <label key={key} className="block">
              <span className="mb-1 block text-sm font-medium capitalize text-slate-700">
                {key.replace('_', ' ')}
              </span>
              {key === 'bio' ? (
                <textarea
                  rows={3}
                  value={form[key]}
                  onChange={(event) => {
                    setForm((current) => ({ ...current, [key]: event.target.value }));
                  }}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
              ) : (
                <input
                  value={form[key]}
                  onChange={(event) => {
                    setForm((current) => ({ ...current, [key]: event.target.value }));
                  }}
                  className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                />
              )}
            </label>
          ))}

          {update.isError && <ErrorState title="Could not save" message={update.error.message} />}
          {saved && <p className="text-sm text-emerald-700">Saved.</p>}

          <button
            type="submit"
            disabled={update.isPending}
            className="self-start rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white disabled:opacity-60"
          >
            {update.isPending ? 'Saving…' : 'Save changes'}
          </button>
        </form>
      </Panel>

      <Panel title="Visibility">
        <p className="text-sm text-slate-600">
          A private profile shows only your username to visitors — no name, no company, no
          project list. Your public projects stay visible either way; your name simply is not
          linked to them.
        </p>
        <button
          type="button"
          disabled={setVisibility.isPending}
          onClick={() => {
            setVisibility.mutate(isPublic ? 'private' : 'public', { onSuccess: refresh });
          }}
          className="mt-3 rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-60"
        >
          {isPublic ? 'Make my profile private' : 'Make my profile public'}
        </button>
      </Panel>
    </div>
  );
}
