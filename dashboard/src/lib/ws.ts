/**
 * The realtime client: a reconnecting, typed WebSocket over `/api/v1/ws`.
 *
 * The governing rule from `Realtime-Events.md` is that **the dashboard must be
 * correct with WebSocket entirely disabled**. Everything here is an
 * optimisation over TanStack Query's 60-second poll, never the only path to
 * truth — so every failure mode below degrades to "no push", never to "wrong
 * data" and never to a thrown error a page has to handle.
 *
 * Three behaviours are deliberate:
 *
 * - **Backoff has jitter.** Without it, a server restart brings every client
 *   back at the same instant and the reconnect storm knocks it over again.
 * - **Subscriptions are re-sent on every open.** The server keeps no memory of
 *   a dropped socket, so the client owns the intent and replays it.
 * - **A heartbeat exists because a dead TCP connection looks identical to an
 *   idle one.** Two missed pongs and the socket is replaced rather than
 *   silently delivering nothing.
 */

/** Every server-to-client event type from `Realtime-Events.md`. */
export type RealtimeEventType =
  | 'connection.ready'
  | 'image.received'
  | 'image.processing'
  | 'image.rejected'
  | 'prediction.completed'
  | 'project.progress.updated'
  | 'project.status.changed'
  | 'project.approval.required'
  | 'project.approved'
  | 'device.status.changed'
  | 'device.paired'
  | 'remark.created'
  | 'report.ready'
  | 'notification.created';

/** The envelope every event arrives in. */
export interface RealtimeEvent {
  type: RealtimeEventType;
  project_id: string;
  ts: string;
  payload: Record<string, unknown>;
}

export type ConnectionState = 'connecting' | 'open' | 'closed';

export interface RealtimeClientOptions {
  /** Returns a current access token, or null when signed out. */
  getToken: () => string | null;
  onEvent: (event: RealtimeEvent) => void;
  onStateChange?: (state: ConnectionState) => void;
  /** Injected in tests; defaults to the global `WebSocket`. */
  socketFactory?: (url: string) => WebSocket;
  url?: string;
}

const HEARTBEAT_MS = 25_000;
const PONG_GRACE_MS = 10_000;
const MAX_MISSED_PONGS = 2;
const BASE_BACKOFF_MS = 1_000;
const MAX_BACKOFF_MS = 30_000;

function isRealtimeEvent(value: unknown): value is RealtimeEvent {
  if (typeof value !== 'object' || value === null) return false;
  const candidate = value as Record<string, unknown>;
  return typeof candidate['type'] === 'string' && typeof candidate['project_id'] === 'string';
}

/**
 * Backoff with full jitter: a random point in `[0, capped)`.
 *
 * Full rather than partial jitter because the failure being defended against
 * is synchronised clients, and partial jitter still leaves them clustered.
 */
export function backoffDelay(attempt: number, random: () => number = Math.random): number {
  const capped = Math.min(BASE_BACKOFF_MS * 2 ** attempt, MAX_BACKOFF_MS);
  return Math.round(random() * capped);
}

export class RealtimeClient {
  private socket: WebSocket | null = null;
  private readonly subscriptions = new Set<string>();
  private attempt = 0;
  private missedPongs = 0;
  private heartbeat: ReturnType<typeof setInterval> | null = null;
  private pongTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;

  constructor(private readonly options: RealtimeClientOptions) {}

  /** Open the socket, if a token is available. */
  connect(): void {
    this.stopped = false;
    const token = this.options.getToken();
    if (!token) return;

    this.options.onStateChange?.('connecting');
    const base = this.options.url ?? defaultUrl();
    const socket = (this.options.socketFactory ?? ((url) => new WebSocket(url)))(
      `${base}?token=${encodeURIComponent(token)}`,
    );
    this.socket = socket;

    socket.onopen = () => {
      this.attempt = 0;
      this.missedPongs = 0;
      this.options.onStateChange?.('open');
      // The server has no memory of the socket that just died, so the client
      // replays what it wants to follow.
      this.flushSubscriptions();
      this.startHeartbeat();
    };

    socket.onmessage = (message: MessageEvent<string>) => {
      let data: unknown;
      try {
        data = JSON.parse(message.data);
      } catch {
        return; // A malformed frame is not worth dropping the connection over.
      }
      if (typeof data === 'object' && data !== null && (data as { type?: string }).type === 'pong') {
        this.missedPongs = 0;
        if (this.pongTimer) clearTimeout(this.pongTimer);
        return;
      }
      if (isRealtimeEvent(data)) this.options.onEvent(data);
    };

    socket.onclose = () => {
      this.teardown();
      this.options.onStateChange?.('closed');
      this.scheduleReconnect();
    };

    socket.onerror = () => {
      // `onclose` always follows, and that is where reconnection is handled;
      // doing it here too would schedule two reconnects for one failure.
    };
  }

  /** Follow these projects, now and after every reconnect. */
  subscribe(projectIds: string[]): void {
    let added = false;
    for (const id of projectIds) {
      if (!this.subscriptions.has(id)) {
        this.subscriptions.add(id);
        added = true;
      }
    }
    if (added) this.flushSubscriptions();
  }

  /** Stop following these projects. */
  unsubscribe(projectIds: string[]): void {
    for (const id of projectIds) this.subscriptions.delete(id);
    this.send({ type: 'unsubscribe', payload: { project_ids: projectIds } });
  }

  /** Close for good; no reconnect will be scheduled. */
  close(): void {
    this.stopped = true;
    if (this.reconnectTimer) clearTimeout(this.reconnectTimer);
    this.reconnectTimer = null;
    this.teardown();
    this.socket?.close();
    this.socket = null;
  }

  get state(): ConnectionState {
    if (!this.socket) return 'closed';
    return this.socket.readyState === 1 ? 'open' : 'connecting';
  }

  private flushSubscriptions(): void {
    if (this.subscriptions.size === 0) return;
    this.send({ type: 'subscribe', payload: { project_ids: [...this.subscriptions] } });
  }

  private send(message: unknown): void {
    if (this.socket?.readyState !== 1) return;
    this.socket.send(JSON.stringify(message));
  }

  private startHeartbeat(): void {
    this.stopHeartbeat();
    this.heartbeat = setInterval(() => {
      this.send({ type: 'ping' });
      this.pongTimer = setTimeout(() => {
        this.missedPongs += 1;
        if (this.missedPongs >= MAX_MISSED_PONGS) {
          // A half-open TCP connection reads exactly like an idle one, so the
          // only way to tell is to stop hearing back.
          this.socket?.close();
        }
      }, PONG_GRACE_MS);
    }, HEARTBEAT_MS);
  }

  private stopHeartbeat(): void {
    if (this.heartbeat) clearInterval(this.heartbeat);
    if (this.pongTimer) clearTimeout(this.pongTimer);
    this.heartbeat = null;
    this.pongTimer = null;
  }

  private teardown(): void {
    this.stopHeartbeat();
  }

  private scheduleReconnect(): void {
    if (this.stopped) return;
    const delay = backoffDelay(this.attempt);
    this.attempt += 1;
    this.reconnectTimer = setTimeout(() => {
      this.connect();
    }, delay);
  }
}

function defaultUrl(): string {
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${protocol}//${window.location.host}/api/v1/ws`;
}
