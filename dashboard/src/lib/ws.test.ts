/**
 * The realtime client's protocol behaviour.
 *
 * These cover what the backend tests deliberately cannot: frames, reconnection,
 * the heartbeat, and — the one that matters most — that **subscriptions are
 * replayed after a reconnect**. The server keeps no memory of a dropped socket,
 * so a client that forgets to re-subscribe goes permanently quiet while looking
 * perfectly healthy.
 */

import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

import { RealtimeClient, backoffDelay, type RealtimeEvent } from '@/lib/ws';

/** A WebSocket stand-in whose lifecycle the test drives. */
class FakeSocket {
  static instances: FakeSocket[] = [];

  readyState = 0;
  sent: string[] = [];
  closed = false;
  onopen: (() => void) | null = null;
  onclose: (() => void) | null = null;
  onerror: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;

  constructor(readonly url: string) {
    FakeSocket.instances.push(this);
  }

  open() {
    this.readyState = 1;
    this.onopen?.();
  }

  receive(data: unknown) {
    this.onmessage?.({ data: JSON.stringify(data) } as MessageEvent<string>);
  }

  receiveRaw(data: string) {
    this.onmessage?.({ data } as MessageEvent<string>);
  }

  send(payload: string) {
    this.sent.push(payload);
  }

  close() {
    this.closed = true;
    this.readyState = 3;
    this.onclose?.();
  }

  get frames(): { type: string; payload?: { project_ids?: string[] } }[] {
    return this.sent.map((raw) => JSON.parse(raw) as { type: string });
  }
}

const PROJECT = '11111111-1111-4111-8111-111111111111';

function makeClient(events: RealtimeEvent[] = [], token: string | null = 'token-abc') {
  const states: string[] = [];
  const client = new RealtimeClient({
    getToken: () => token,
    onEvent: (event) => events.push(event),
    onStateChange: (state) => states.push(state),
    socketFactory: (url) => new FakeSocket(url) as unknown as WebSocket,
    url: 'ws://test/api/v1/ws',
  });
  return { client, states };
}

beforeEach(() => {
  FakeSocket.instances = [];
  vi.useFakeTimers();
});

afterEach(() => {
  vi.useRealTimers();
});

describe('backoffDelay', () => {
  it('grows exponentially and is capped at 30 seconds', () => {
    const ceiling = (attempt: number) => backoffDelay(attempt, () => 1);
    expect(ceiling(0)).toBe(1000);
    expect(ceiling(1)).toBe(2000);
    expect(ceiling(3)).toBe(8000);
    expect(ceiling(10)).toBe(30_000);
  });

  it('applies full jitter so clients do not reconnect in lockstep', () => {
    // A server restart brings every client back at once; without jitter the
    // reconnect storm knocks it over again.
    expect(backoffDelay(5, () => 0)).toBe(0);
    expect(backoffDelay(5, () => 0.5)).toBeLessThan(backoffDelay(5, () => 1));
  });
});

describe('connecting', () => {
  it('puts the token in the query string, as browsers cannot set headers', () => {
    const { client } = makeClient();
    client.connect();
    expect(FakeSocket.instances[0]?.url).toBe('ws://test/api/v1/ws?token=token-abc');
  });

  it('does not open a socket without a token', () => {
    const { client } = makeClient([], null);
    client.connect();
    expect(FakeSocket.instances).toHaveLength(0);
  });

  it('reports its state transitions', () => {
    const { client, states } = makeClient();
    client.connect();
    FakeSocket.instances[0]?.open();
    expect(states).toEqual(['connecting', 'open']);
  });
});

describe('subscriptions', () => {
  it('sends the subscription once open', () => {
    const { client } = makeClient();
    client.connect();
    const socket = FakeSocket.instances[0];
    socket?.open();
    client.subscribe([PROJECT]);

    const subscribe = socket?.frames.find((frame) => frame.type === 'subscribe');
    expect(subscribe?.payload?.project_ids).toEqual([PROJECT]);
  });

  it('replays subscriptions after a reconnect', () => {
    // The server forgets a dropped socket entirely, so the client owns the
    // intent. Without this the UI goes quiet while looking connected.
    const { client } = makeClient();
    client.connect();
    const first = FakeSocket.instances[0];
    first?.open();
    client.subscribe([PROJECT]);

    first?.close();
    vi.advanceTimersByTime(31_000);
    const second = FakeSocket.instances[1];
    second?.open();

    expect(second?.frames.some((frame) => frame.type === 'subscribe')).toBe(true);
  });

  it('does not resend an id it already follows', () => {
    const { client } = makeClient();
    client.connect();
    const socket = FakeSocket.instances[0];
    socket?.open();
    client.subscribe([PROJECT]);
    client.subscribe([PROJECT]);

    expect(socket?.frames.filter((frame) => frame.type === 'subscribe')).toHaveLength(1);
  });

  it('queues a subscription made before the socket opens', () => {
    const { client } = makeClient();
    client.subscribe([PROJECT]);
    client.connect();
    const socket = FakeSocket.instances[0];
    socket?.open();

    expect(socket?.frames.some((frame) => frame.type === 'subscribe')).toBe(true);
  });
});

describe('events', () => {
  it('delivers a well-formed event', () => {
    const received: RealtimeEvent[] = [];
    const { client } = makeClient(received);
    client.connect();
    const socket = FakeSocket.instances[0];
    socket?.open();
    socket?.receive({
      type: 'project.progress.updated',
      project_id: PROJECT,
      ts: '2026-08-15T07:00:00Z',
      payload: { displayed_pct: 38.5 },
    });

    expect(received).toHaveLength(1);
    expect(received[0]?.payload['displayed_pct']).toBe(38.5);
  });

  it('ignores an unparseable frame rather than dropping the connection', () => {
    const received: RealtimeEvent[] = [];
    const { client } = makeClient(received);
    client.connect();
    const socket = FakeSocket.instances[0];
    socket?.open();
    socket?.receiveRaw('{not json');

    expect(received).toHaveLength(0);
    expect(socket?.closed).toBe(false);
  });

  it('does not surface a pong as an application event', () => {
    const received: RealtimeEvent[] = [];
    const { client } = makeClient(received);
    client.connect();
    const socket = FakeSocket.instances[0];
    socket?.open();
    socket?.receive({ type: 'pong' });

    expect(received).toHaveLength(0);
  });
});

describe('heartbeat', () => {
  it('pings on a schedule', () => {
    const { client } = makeClient();
    client.connect();
    const socket = FakeSocket.instances[0];
    socket?.open();

    vi.advanceTimersByTime(25_000);
    expect(socket?.frames.some((frame) => frame.type === 'ping')).toBe(true);
  });

  it('replaces the socket after two unanswered pings', () => {
    // A half-open TCP connection reads exactly like an idle one; not hearing
    // back is the only signal available.
    const { client } = makeClient();
    client.connect();
    const socket = FakeSocket.instances[0];
    socket?.open();

    vi.advanceTimersByTime(25_000 + 10_000);
    vi.advanceTimersByTime(25_000 + 10_000);

    expect(socket?.closed).toBe(true);
  });

  it('a pong clears the missed count', () => {
    const { client } = makeClient();
    client.connect();
    const socket = FakeSocket.instances[0];
    socket?.open();

    vi.advanceTimersByTime(25_000);
    socket?.receive({ type: 'pong' });
    vi.advanceTimersByTime(10_000);

    expect(socket?.closed).toBe(false);
  });
});

describe('closing', () => {
  it('stops reconnecting once closed deliberately', () => {
    const { client } = makeClient();
    client.connect();
    FakeSocket.instances[0]?.open();
    client.close();

    vi.advanceTimersByTime(60_000);
    expect(FakeSocket.instances).toHaveLength(1);
  });

  it('reconnects after an unexpected close', () => {
    const { client } = makeClient();
    client.connect();
    FakeSocket.instances[0]?.open();
    FakeSocket.instances[0]?.close();

    vi.advanceTimersByTime(31_000);
    expect(FakeSocket.instances.length).toBeGreaterThan(1);
  });
});
