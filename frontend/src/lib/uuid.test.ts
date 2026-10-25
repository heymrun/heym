import { afterEach, describe, expect, it, vi } from "vitest";

import { randomUUID } from "@/lib/uuid";

const V4 = /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

describe("randomUUID", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("uses the browser's own when it exists", () => {
    expect(randomUUID()).toMatch(V4);
  });

  it("builds a v4 UUID where the page is not a secure context", () => {
    const real = globalThis.crypto;
    vi.stubGlobal("crypto", { getRandomValues: real.getRandomValues.bind(real) });
    const ids = new Set([randomUUID(), randomUUID(), randomUUID()]);
    expect(ids.size).toBe(3);
    for (const id of ids) expect(id).toMatch(V4);
  });
});
