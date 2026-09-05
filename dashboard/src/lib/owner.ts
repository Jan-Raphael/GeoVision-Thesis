/**
 * The authenticated surface: types, calls, and query hooks.
 *
 * The `permissions` block on a folder is the important one. It is a
 * `dict[str, bool]` computed server-side for *this* caller, and every action
 * button is rendered from it — never from a role guessed in the client. Hiding
 * a button is not security (the API enforces it too); it is honesty, so a
 * viewer is not offered an action that will fail.
 */

import { useMutation, useQuery, useQueryClient, type UseQueryResult } from '@tanstack/react-query';

import type {
  CaptureSummary,
  MacroStage,
  ProjectStatus,
  PublicRemark,
  StageBreakdown,
  TimelinePoint,
} from '@/lib/api';
import { authed } from '@/lib/auth';

export interface Member {
  id: string;
  user_id: string;
  username: string | null;
  full_name: string | null;
  professional_role: string | null;
  membership_role: string;
  membership_status: string;
}

export interface Device {
  id: string;
  device_name: string;
  face: string;
  status: 'unpaired' | 'paired' | 'online' | 'offline' | 'revoked';
  weight: number;
  last_seen_at: string | null;
  last_battery_mv: number | null;
  last_rssi_dbm: number | null;
}

export interface Asset {
  id: string;
  kind: string;
  original_filename: string;
  size_bytes: number;
  notes: string | null;
  is_public: boolean;
  download_url: string | null;
}

/** Everything the owner folder page renders. */
export interface ProjectFolder {
  id: string;
  project_code: string;
  name: string;
  intended_use: string | null;
  description: string | null;
  location_label: string;
  latitude: number;
  longitude: number;
  map_url: string;
  osm_url: string;
  start_date: string;
  deadline_date: string;
  days_remaining: number;
  worker_count: number | null;
  visibility: 'public' | 'private';
  status: ProjectStatus;
  status_reason: string;
  approval_state: 'not_ready' | 'awaiting_inspection' | 'approved';
  progress_pct: number;
  expected_pct: number;
  macro_stage: MacroStage | null;
  stages: StageBreakdown;
  members: Member[];
  devices: Device[];
  recent_images: CaptureSummary[];
  remarks: PublicRemark[];
  assets: Asset[];
  timeline: TimelinePoint[];
  last_capture_at: string | null;
  inspection_notes: string | null;
  /** What *this* caller may do. Every action button reads from here. */
  permissions: Record<string, boolean>;
}

export interface ProjectSummary {
  id: string;
  project_code: string;
  name: string;
  location_label: string;
  progress_pct: number;
  macro_stage: MacroStage | null;
  status: ProjectStatus;
  visibility: 'public' | 'private';
  deadline_date: string;
  last_capture_at: string | null;
}

export interface PairingTicket {
  display_code: string;
  formatted_code: string;
  expires_at: string;
  expires_in_seconds: number;
  project_code: string;
  face: string;
  device_name: string;
  qr_png_base64: string | null;
  pair_page_url: string;
  pair_page_qr_base64: string | null;
}

export interface CreateProjectInput {
  name: string;
  code_initials: string;
  project_number: number;
  location_label: string;
  latitude: number;
  longitude: number;
  start_date: string;
  deadline_date: string;
  visibility: 'public' | 'private';
  intended_use?: string;
  worker_count?: number;
}

export const ownerKeys = {
  myProjects: () => ['owner', 'projects'] as const,
  folder: (id: string) => ['owner', 'folder', id] as const,
};

// ---------------------------------------------------------------------------
// Queries
// ---------------------------------------------------------------------------

/**
 * `refetchInterval` is the WebSocket fallback promised in `Realtime-Events.md`:
 * with the socket down the folder still converges within a minute, so realtime
 * stays an optimisation and never the only path to truth.
 */
export function useMyProjects(): UseQueryResult<ProjectSummary[]> {
  return useQuery({
    queryKey: ownerKeys.myProjects(),
    queryFn: () => authed<ProjectSummary[]>('/projects'),
  });
}

export function useFolder(projectId: string): UseQueryResult<ProjectFolder> {
  return useQuery({
    queryKey: ownerKeys.folder(projectId),
    queryFn: () => authed<ProjectFolder>(`/projects/${projectId}`),
    enabled: projectId.length > 0,
    refetchInterval: 60_000,
  });
}

// ---------------------------------------------------------------------------
// Mutations
// ---------------------------------------------------------------------------

export function useCreateProject() {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateProjectInput) =>
      authed<ProjectSummary>('/projects', { method: 'POST', body: input }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ownerKeys.myProjects() }),
  });
}

/** Check a project code's availability, for the live preview on the form. */
export async function checkCode(initials: string, projectNumber: number): Promise<boolean> {
  if (initials.length < 2) return false;
  try {
    await authed(`/projects/${initials.toUpperCase()}_${String(projectNumber).padStart(2, '0')}`);
    return false;
  } catch {
    // A 404 here means "free". Any other failure is treated the same way: the
    // server re-checks on submit and answers 409 with suggestions, so an
    // optimistic "available" costs nothing worse than a corrected form.
    return true;
  }
}

export function useApproveProject(projectId: string) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (inspectionNotes: string) =>
      authed<ProjectSummary>(`/projects/${projectId}/approve`, {
        method: 'POST',
        body: { inspection_notes: inspectionNotes },
      }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ownerKeys.folder(projectId) }),
  });
}

export function useCreateRemark(projectId: string) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (input: { message: string; remark_type: string; severity: string }) =>
      authed(`/projects/${projectId}/remarks`, {
        method: 'POST',
        body: { ...input, is_public: false },
      }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ownerKeys.folder(projectId) }),
  });
}

export function useIssuePairingToken(projectId: string) {
  return useMutation({
    mutationFn: (face: string) =>
      authed<PairingTicket>(`/projects/${projectId}/pairing-tokens`, {
        method: 'POST',
        body: { face },
      }),
  });
}

export function useRequestReport(projectId: string) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (input: { kind: string; report_format: string }) =>
      authed(`/projects/${projectId}/reports`, { method: 'POST', body: input }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ownerKeys.folder(projectId) }),
  });
}

// ---------------------------------------------------------------------------
// Members, invitations, devices, assets, profile
// ---------------------------------------------------------------------------

export interface Invitation {
  id: string;
  project_id: string;
  project_name?: string;
  project_code?: string;
  membership_role: string;
  membership_status: string;
  invited_at: string | null;
}

export const inviteKeys = {
  invitations: () => ['owner', 'invitations'] as const,
  assets: (id: string) => ['owner', 'assets', id] as const,
};

export function useInvitations(): UseQueryResult<Invitation[]> {
  return useQuery({
    queryKey: inviteKeys.invitations(),
    queryFn: () => authed<Invitation[]>('/invitations'),
  });
}

/** Accept or decline. One mutation, because they are the same decision. */
export function useRespondToInvitation() {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: ({ memberId, accept }: { memberId: string; accept: boolean }) =>
      authed(`/invitations/${memberId}`, { method: 'POST', body: { accept } }),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: inviteKeys.invitations() });
      void cache.invalidateQueries({ queryKey: ownerKeys.myProjects() });
    },
  });
}

export function useInviteMember(projectId: string) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (input: { identifier: string; membership_role: string }) =>
      authed(`/projects/${projectId}/members`, { method: 'POST', body: input }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ownerKeys.folder(projectId) }),
  });
}

export function useChangeMemberRole(projectId: string) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: ({ memberId, role }: { memberId: string; role: string }) =>
      authed(`/projects/${projectId}/members/${memberId}`, {
        method: 'PATCH',
        body: { membership_role: role },
      }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ownerKeys.folder(projectId) }),
  });
}

export function useRemoveMember(projectId: string) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (memberId: string) =>
      authed(`/projects/${projectId}/members/${memberId}`, { method: 'DELETE' }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ownerKeys.folder(projectId) }),
  });
}

export function useUpdateDevice(projectId: string) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: ({ deviceId, settings }: { deviceId: string; settings: Record<string, unknown> }) =>
      authed(`/projects/${projectId}/devices/${deviceId}`, { method: 'PATCH', body: settings }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ownerKeys.folder(projectId) }),
  });
}

/**
 * Unpair revokes the camera's secret. Its **images are kept** — they are the
 * project's evidence, and losing them because a camera was swapped would be a
 * far worse outcome than an orphaned device row.
 */
export function useUnpairDevice(projectId: string) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (deviceId: string) =>
      authed(`/projects/${projectId}/devices/${deviceId}/unpair`, { method: 'POST' }),
    onSuccess: () => cache.invalidateQueries({ queryKey: ownerKeys.folder(projectId) }),
  });
}

export function useUploadAsset(projectId: string) {
  const cache = useQueryClient();
  return useMutation({
    mutationFn: ({ file, kind, notes }: { file: File; kind: string; notes: string }) => {
      const form = new FormData();
      form.append('file', file);
      form.append('kind', kind);
      if (notes) form.append('notes', notes);
      return authed<Asset>(`/projects/${projectId}/assets`, { method: 'POST', form });
    },
    onSuccess: () => cache.invalidateQueries({ queryKey: ownerKeys.folder(projectId) }),
  });
}

export interface ProfileUpdate {
  full_name?: string;
  company?: string;
  bio?: string;
  professional_role?: string;
}

export function useUpdateProfile() {
  return useMutation({
    mutationFn: (input: ProfileUpdate) => authed('/users/me', { method: 'PATCH', body: input }),
  });
}

export function useSetProfileVisibility() {
  return useMutation({
    mutationFn: (visibility: 'public' | 'private') =>
      authed('/users/me/visibility', {
        method: 'PATCH',
        body: { profile_visibility: visibility },
      }),
  });
}

/** One capture with its prediction and detection boxes, for the lightbox. */
export interface ImageDetail {
  id: string;
  filename: string;
  captured_at: string;
  status: string;
  latitude: number | null;
  longitude: number | null;
  original_url: string | null;
  thumb_url: string | null;
  map_url: string | null;
  rejected_reason: string | null;
  counts: Record<string, number>;
  prediction: {
    stage: string;
    confidence: number;
    macro_stage: string;
    raw_progress_pct: number;
    is_eligible: boolean;
    low_confidence: boolean;
    class_probabilities: Record<string, number>;
  } | null;
  detections: {
    class_name: string;
    confidence: number;
    bbox: { x: number; y: number; width: number; height: number };
  }[];
}

export function useImageDetail(projectId: string, imageId: string | null) {
  return useQuery({
    queryKey: ['owner', 'image', projectId, imageId] as const,
    queryFn: () => authed<ImageDetail>(`/projects/${projectId}/images/${imageId ?? ''}`),
    enabled: Boolean(imageId),
  });
}
