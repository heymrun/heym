import type { ClientMessage, ServerMessage } from "@/features/collab/types";

const RECONNECT_MIN_MS = 1000;
const RECONNECT_MAX_MS = 30_000;
const MAX_QUEUED_MESSAGES = 500;
/** The server closed for a reason reconnecting cannot fix. */
const FINAL_CLOSE_CODES = new Set([4401, 4403, 4429]);

export type CollabStatus = "connecting" | "open" | "closed";

export interface CollabClientOptions {
  url: string;
  onMessage: (message: ServerMessage) => void;
  onStatus: (status: CollabStatus) => void;
  /** Called once when the room cannot be reached; the editor carries on without it. */
  onUnavailable: (reason: string) => void;
}

export function collabSocketUrl(workflowId: string): string {
  const base = (import.meta.env.VITE_API_URL as string | undefined) || window.location.origin;
  return `${base.replace(/^http/, "ws")}/api/workflows/${workflowId}/collab`;
}

/** One reconnecting WebSocket to a canvas room. */
export class CollabClient {
  private socket: WebSocket | null = null;
  private queue: string[] = [];
  private retryMs = RECONNECT_MIN_MS;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private stopped = false;
  private opened = false;
  private reported = false;

  constructor(private readonly options: CollabClientOptions) {}

  start(): void {
    this.stopped = false;
    this.connect();
  }

  stop(): void {
    this.stopped = true;
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.retryTimer = null;
    const socket = this.socket;
    this.socket = null;
    socket?.close(1000);
    this.queue = [];
  }

  get isOpen(): boolean {
    return this.socket?.readyState === WebSocket.OPEN;
  }

  /** Sends now, or queues while disconnected when `queueWhileClosed` is set. */
  send(message: ClientMessage, queueWhileClosed = false): void {
    const text = JSON.stringify(message);
    if (this.socket && this.isOpen) {
      this.socket.send(text);
      return;
    }
    if (queueWhileClosed && this.queue.length < MAX_QUEUED_MESSAGES) this.queue.push(text);
  }

  /** Sends what was queued while disconnected; live sync calls it once it has caught up. */
  flushQueue(): void {
    while (this.socket && this.isOpen && this.queue.length > 0) {
      const text = this.queue.shift();
      if (text !== undefined) this.socket.send(text);
    }
  }

  private reportUnavailable(reason: string): void {
    if (this.reported) return;
    this.reported = true;
    this.options.onUnavailable(reason);
  }

  private scheduleRetry(): void {
    if (this.stopped) return;
    this.retryTimer = setTimeout(() => this.connect(), this.retryMs);
    this.retryMs = Math.min(this.retryMs * 2, RECONNECT_MAX_MS);
  }

  private connect(): void {
    this.options.onStatus("connecting");
    let socket: WebSocket;
    try {
      // Throws at once for a blocked or malformed address (an https page reaching ws://).
      socket = new WebSocket(this.options.url);
    } catch (error) {
      this.socket = null;
      this.options.onStatus("closed");
      this.reportUnavailable(error instanceof Error ? error.message : "connection refused");
      this.scheduleRetry();
      return;
    }
    this.socket = socket;
    socket.onopen = (): void => {
      this.retryMs = RECONNECT_MIN_MS;
      this.opened = true;
      this.options.onStatus("open");
    };
    socket.onmessage = (event: MessageEvent): void => {
      if (typeof event.data !== "string") return;
      let message: ServerMessage;
      try {
        message = JSON.parse(event.data) as ServerMessage;
      } catch {
        return;
      }
      this.options.onMessage(message);
    };
    socket.onclose = (event: CloseEvent): void => {
      if (this.socket !== socket) return;
      this.socket = null;
      this.options.onStatus("closed");
      if (this.stopped) return;
      if (FINAL_CLOSE_CODES.has(event.code)) {
        this.reportUnavailable(`refused (${event.code})`);
        return;
      }
      // Never reached the room: say so once, then keep trying quietly in case it comes back.
      if (!this.opened) this.reportUnavailable("could not connect");
      this.scheduleRetry();
    };
  }
}
