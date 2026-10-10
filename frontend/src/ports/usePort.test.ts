import { createApp, type App, type InjectionKey } from "vue";
import { describe, expect, it } from "vitest";

import { usePort } from "@/ports";

const samplePortKey: InjectionKey<{ ping: () => string }> = Symbol("samplePort");

function hostApp(): App {
  return createApp({});
}

describe("usePort", () => {
  it("returns what the host provided", () => {
    const app = hostApp();
    app.provide(samplePortKey, { ping: () => "pong" });

    expect(app.runWithContext(() => usePort(samplePortKey).ping())).toBe("pong");
  });

  it("names the port the host did not provide", () => {
    const app = hostApp();

    expect(() => app.runWithContext(() => usePort(samplePortKey))).toThrow(
      "samplePort is not provided",
    );
  });
});
