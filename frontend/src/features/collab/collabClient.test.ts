import { afterEach, describe, expect, it, vi } from "vitest";

import { CollabClient } from "@/features/collab/collabClient";

class ThrowingSocket {
  constructor() {
    throw new Error("An insecure WebSocket connection may not be initiated");
  }
}

class ClosingSocket {
  static OPEN = 1;
  readyState = 0;
  onopen: (() => void) | null = null;
  onmessage: (() => void) | null = null;
  onclose: ((event: { code: number }) => void) | null = null;

  constructor() {
    setTimeout(() => this.onclose?.({ code: 1006 }), 0);
  }

  close(): void {}
}

describe("CollabClient", () => {
  const original = globalThis.WebSocket;

  afterEach(() => {
    globalThis.WebSocket = original;
    vi.useRealTimers();
  });

  it("reports an unavailable socket once instead of throwing", () => {
    vi.useFakeTimers();
    globalThis.WebSocket = ThrowingSocket as unknown as typeof WebSocket;
    const onUnavailable = vi.fn();
    const client = new CollabClient({
      url: "ws://example.invalid/collab",
      onMessage: () => undefined,
      onStatus: () => undefined,
      onUnavailable,
    });

    expect(() => client.start()).not.toThrow();
    vi.advanceTimersByTime(5_000);
    client.stop();

    expect(onUnavailable).toHaveBeenCalledTimes(1);
  });

  it("reports a socket that never opens once, and keeps retrying quietly", () => {
    vi.useFakeTimers();
    let created = 0;
    globalThis.WebSocket = class extends ClosingSocket {
      constructor() {
        super();
        created += 1;
      }
    } as unknown as typeof WebSocket;
    const onUnavailable = vi.fn();
    const client = new CollabClient({
      url: "ws://example.invalid/collab",
      onMessage: () => undefined,
      onStatus: () => undefined,
      onUnavailable,
    });

    client.start();
    vi.advanceTimersByTime(10_000);
    client.stop();

    expect(onUnavailable).toHaveBeenCalledTimes(1);
    expect(created).toBeGreaterThan(1);
  });
});
