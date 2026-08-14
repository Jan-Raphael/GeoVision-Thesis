/**
 * Wires the realtime socket to the TanStack Query cache.
 *
 * This is the piece Module 14 deliberately deferred: the transport was finished
 * and tested, but the caches it patches did not exist until now.
 *
 * The rule it follows is the one from `Realtime-Events.md`: **patch, do not
 * refetch.** An event already carries the new value, so writing it into the
 * cache costs nothing; asking the server again turns one pushed capture into a
 * request from every open tab, which is how a live dashboard becomes a
 * self-inflicted load test. Events that change a *collection* — a new device, a
 * finished report — invalidate instead, because the client cannot construct the
 * new row from the event alone.
 *
 * Nothing here is load-bearing. The folder query polls every 60 s, so a socket
 * that never connects costs freshness and nothing else.
 */

import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef } from 'react';

import { accessToken } from '@/lib/auth';
import { ownerKeys, type ProjectFolder } from '@/lib/owner';
import { RealtimeClient, type RealtimeEvent } from '@/lib/ws';

export interface RealtimeOptions {
  /** Projects to follow. Usually the one folder that is open. */
  projectIds: string[];
  /** Fired for every event, after the cache is patched — used for toasts. */
  onEvent?: (event: RealtimeEvent) => void;
}

/**
 * Open a socket for the lifetime of the component and keep the cache fresh.
 *
 * The client is held in a ref rather than state: reconnects and heartbeats must
 * not re-render the tree, and a socket recreated on every render would spend
 * its life reconnecting.
 */
export function useRealtime({ projectIds, onEvent }: RealtimeOptions): void {
  const cache = useQueryClient();
  const client = useRef<RealtimeClient | null>(null);
  const handler = useRef(onEvent);
  handler.current = onEvent;

  useEffect(() => {
    if (!accessToken()) return undefined;

    const realtime = new RealtimeClient({
      getToken: accessToken,
      onEvent: (event) => {
        patch(cache, event);
        handler.current?.(event);
      },
    });
    client.current = realtime;
    realtime.connect();

    return () => {
      realtime.close();
      client.current = null;
    };
  }, [cache]);

  // Separate from the connection effect so opening a second project does not
  // tear down and rebuild the socket.
  useEffect(() => {
    if (projectIds.length > 0) client.current?.subscribe(projectIds);
  }, [projectIds]);
}

type Cache = ReturnType<typeof useQueryClient>;

/** Apply one event to the cache. See the map in `Module-14-Realtime.md`. */
export { patch as __patchForTest };

function patch(cache: Cache, event: RealtimeEvent): void {
  const key = ownerKeys.folder(event.project_id);

  switch (event.type) {
    case 'project.progress.updated': {
      const stages = event.payload['stages'];
      cache.setQueryData<ProjectFolder>(key, (folder) =>
        folder
          ? {
              ...folder,
              progress_pct: numberOr(event.payload['displayed_pct'], folder.progress_pct),
              macro_stage:
                (event.payload['macro_stage'] as ProjectFolder['macro_stage']) ??
                folder.macro_stage,
              stages: isStages(stages) ? stages : folder.stages,
            }
          : folder,
      );
      return;
    }

    case 'project.status.changed': {
      cache.setQueryData<ProjectFolder>(key, (folder) =>
        folder
          ? {
              ...folder,
              status: isStatus(event.payload['new']) ? event.payload['new'] : folder.status,
            }
          : folder,
      );
      return;
    }

    case 'project.approval.required': {
      cache.setQueryData<ProjectFolder>(key, (folder) =>
        folder ? { ...folder, approval_state: 'awaiting_inspection' } : folder,
      );
      return;
    }

    case 'image.received':
    case 'prediction.completed':
    case 'image.rejected':
    case 'device.paired':
    case 'device.status.changed':
    case 'remark.created':
    case 'report.ready':
      // These add or replace a row the client cannot build from the payload
      // alone — a capture needs its signed thumbnail URL, a device its derived
      // liveness. One refetch of the folder is cheaper and always correct.
      void cache.invalidateQueries({ queryKey: key });
      return;

    default:
      return;
  }
}

function numberOr(value: unknown, fallback: number): number {
  return typeof value === 'number' ? value : fallback;
}

function isStatus(value: unknown): value is ProjectFolder['status'] {
  return (
    typeof value === 'string' &&
    ['active', 'inactive', 'delayed', 'completed', 'archived'].includes(value)
  );
}

function isStages(value: unknown): value is ProjectFolder['stages'] {
  return typeof value === 'object' && value !== null && 'foundation_pct' in value;
}
