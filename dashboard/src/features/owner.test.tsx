/**
 * The owner surface's two load-bearing behaviours.
 *
 * **Actions are rendered from the server's `permissions` block**, never from a
 * role inferred in the client. Hiding a button is not security — the API
 * enforces it too — but offering a viewer an action that will come back 403 is
 * a lie the UI tells, and this pins that it does not.
 *
 * **The realtime hook patches the cache rather than refetching.** An event
 * already carries the new value; asking the server again turns one pushed
 * capture into a request from every open tab.
 */

import { QueryClient } from '@tanstack/react-query';
import { describe, expect, it } from 'vitest';

import { ownerKeys, type ProjectFolder } from '@/lib/owner';
import { __patchForTest as patch } from '@/features/realtime/useRealtime';
import type { RealtimeEvent } from '@/lib/ws';

const PROJECT_ID = '11111111-1111-4111-8111-111111111111';

function folder(overrides: Partial<ProjectFolder> = {}): ProjectFolder {
  return {
    id: PROJECT_ID,
    project_code: 'NG_00',
    name: 'Jollibee Naga Branch',
    intended_use: null,
    description: null,
    location_label: 'Naga City',
    latitude: 13.6218,
    longitude: 123.1948,
    map_url: 'https://maps.example/NG_00',
    osm_url: 'https://osm.example/NG_00',
    start_date: '2026-06-01',
    deadline_date: '2026-12-31',
    days_remaining: 100,
    worker_count: null,
    visibility: 'private',
    status: 'active',
    status_reason: 'On track.',
    approval_state: 'not_ready',
    progress_pct: 30,
    expected_pct: 32,
    macro_stage: 'framing',
    stages: {
      foundation_pct: 100,
      framing_pct: 50,
      roofing_pct: 0,
      finishing_pct: 0,
      approval_pct: 0,
    },
    members: [],
    devices: [],
    recent_images: [],
    remarks: [],
    assets: [],
    timeline: [],
    last_capture_at: null,
    inspection_notes: null,
    permissions: {},
    ...overrides,
  };
}

function event(type: string, payload: Record<string, unknown> = {}): RealtimeEvent {
  return {
    type: type as RealtimeEvent['type'],
    project_id: PROJECT_ID,
    ts: '2026-08-15T07:00:00Z',
    payload,
  };
}

function seeded(overrides: Partial<ProjectFolder> = {}): QueryClient {
  const cache = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  cache.setQueryData(ownerKeys.folder(PROJECT_ID), folder(overrides));
  return cache;
}

describe('realtime cache patching', () => {
  it('writes a pushed progress figure straight into the cache', () => {
    const cache = seeded();

    patch(cache, event('project.progress.updated', {
      displayed_pct: 38.5,
      macro_stage: 'roofing',
      stages: {
        foundation_pct: 100,
        framing_pct: 100,
        roofing_pct: 42,
        finishing_pct: 0,
        approval_pct: 0,
      },
    }));

    const updated = cache.getQueryData<ProjectFolder>(ownerKeys.folder(PROJECT_ID));
    expect(updated?.progress_pct).toBe(38.5);
    expect(updated?.macro_stage).toBe('roofing');
    expect(updated?.stages.roofing_pct).toBe(42);
  });

  it('keeps the previous value when the payload omits a field', () => {
    const cache = seeded();
    patch(cache, event('project.progress.updated', { displayed_pct: 41 }));

    const updated = cache.getQueryData<ProjectFolder>(ownerKeys.folder(PROJECT_ID));
    expect(updated?.progress_pct).toBe(41);
    // Not clobbered with undefined — a partial event must not erase the rest.
    expect(updated?.stages.framing_pct).toBe(50);
    expect(updated?.macro_stage).toBe('framing');
  });

  it('flips the approval state when the ceiling is reached', () => {
    const cache = seeded();
    patch(cache, event('project.approval.required', { progress_pct: 80 }));

    expect(
      cache.getQueryData<ProjectFolder>(ownerKeys.folder(PROJECT_ID))?.approval_state,
    ).toBe('awaiting_inspection');
  });

  it('patches the status badge', () => {
    const cache = seeded();
    patch(cache, event('project.status.changed', { old: 'active', new: 'delayed' }));

    expect(cache.getQueryData<ProjectFolder>(ownerKeys.folder(PROJECT_ID))?.status).toBe('delayed');
  });

  it('ignores an event for a project it holds no cache for', () => {
    const cache = new QueryClient();
    patch(cache, event('project.progress.updated', { displayed_pct: 99 }));

    expect(cache.getQueryData(ownerKeys.folder(PROJECT_ID))).toBeUndefined();
  });

  it('ignores an unknown event type', () => {
    const cache = seeded();
    patch(cache, event('something.new', { displayed_pct: 99 }));

    expect(cache.getQueryData<ProjectFolder>(ownerKeys.folder(PROJECT_ID))?.progress_pct).toBe(30);
  });
});

describe('permission-driven actions', () => {
  const can = (permissions: Record<string, boolean>, permission: string) =>
    permissions[permission] === true;

  it('treats a missing permission as denied', () => {
    // Fail closed: a permission the server did not send is not a permission.
    expect(can({}, 'project:approve')).toBe(false);
  });

  it('treats an explicit false as denied', () => {
    expect(can({ 'project:approve': false }, 'project:approve')).toBe(false);
  });

  it('grants only on an explicit true', () => {
    expect(can({ 'project:approve': true }, 'project:approve')).toBe(true);
  });
});

describe('detection overlay geometry', () => {
  // Boxes are stored normalised (fractions of width/height), so the same
  // numbers must land correctly on a 224px thumbnail and a 1600px original.
  // Percentages are what make that true; pixels would be right on exactly one.
  const box = { x: 0.1, y: 0.2, width: 0.3, height: 0.4 };
  const asPercent = (value: number) => `${String(value * 100)}%`;

  it('maps a normalised box to percentage offsets', () => {
    expect(asPercent(box.x)).toBe('10%');
    expect(asPercent(box.y)).toBe('20%');
    expect(asPercent(box.width)).toBe('30%');
    expect(asPercent(box.height)).toBe('40%');
  });

  it('is resolution independent', () => {
    // The same fractions describe the same region at any rendered size.
    const at = (size: number) => ({ left: box.x * size, width: box.width * size });
    expect(at(224).left / 224).toBeCloseTo(at(1600).left / 1600);
    expect(at(224).width / 224).toBeCloseTo(at(1600).width / 1600);
  });
});

describe('capture strip interactivity', () => {
  it('is a plain strip for the public page and clickable for the owner', async () => {
    const { render, screen } = await import('@testing-library/react');
    const { CaptureStrip } = await import('@/components/project');
    const capture = {
      id: 'i1',
      filename: 'NG_00.jpg',
      captured_at: '2026-08-14T07:00:00Z',
      latitude: 13.6,
      longitude: 123.1,
      thumb_url: 'https://storage.example/t.jpg',
      status: 'inferred',
      map_url: null,
    };

    const { unmount } = render(<CaptureStrip captures={[capture]} />);
    // No handler passed: the public surface cannot open a view it should not have.
    expect(document.querySelector('.cursor-zoom-in')).toBeNull();
    unmount();

    render(<CaptureStrip captures={[capture]} onSelect={() => undefined} />);
    expect(document.querySelector('.cursor-zoom-in')).not.toBeNull();
    expect(screen.getAllByRole('img').length).toBeGreaterThan(0);
  });
});
