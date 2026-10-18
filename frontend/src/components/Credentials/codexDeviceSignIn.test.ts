import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { CodexDeviceSignInPoll, CodexDeviceSignInStart } from "@/types/credential";

import { createCodexDeviceSignIn, type CodexDeviceSignInDeps } from "./codexDeviceSignIn";

const START: CodexDeviceSignInStart = {
  user_code: "ABCD-1234",
  verification_url: "https://auth.openai.com/codex/device",
  interval: 5,
  expires_at: "2999-01-01T00:00:00+00:00",
  state: "sealed-state",
};

const PENDING: CodexDeviceSignInPoll = { status: "pending", config: null, account_id: "" };
const COMPLETE: CodexDeviceSignInPoll = {
  status: "complete",
  config: { auth_mode: "chatgpt", access_token: "at", refresh_token: "rt" },
  account_id: "acct-1",
};

function httpError(status: number, detail: string): Error {
  return Object.assign(new Error(detail), { response: { status, data: { detail } } });
}

function makeDeps(overrides: Partial<CodexDeviceSignInDeps> = {}): CodexDeviceSignInDeps & {
  popup: { close: ReturnType<typeof vi.fn> };
} {
  const popup = { close: vi.fn() };
  return {
    start: vi.fn(async () => START),
    poll: vi.fn(async () => PENDING),
    onSignedIn: vi.fn(),
    openWindow: vi.fn(() => popup as unknown as Window),
    popup,
    ...overrides,
  };
}

describe("createCodexDeviceSignIn", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("shows the code and waits without polling before the first interval", async () => {
    const deps = makeDeps();
    const signIn = createCodexDeviceSignIn(deps);

    await signIn.begin();

    expect(signIn.phase.value).toBe("waiting");
    expect(signIn.userCode.value).toBe("ABCD-1234");
    expect(deps.poll).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(4999);
    expect(deps.poll).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1);
    expect(deps.poll).toHaveBeenCalledWith("sealed-state");
  });

  it("keeps polling while pending, then hands over the config and closes the OpenAI window", async () => {
    const poll = vi
      .fn<CodexDeviceSignInDeps["poll"]>()
      .mockResolvedValueOnce(PENDING)
      .mockResolvedValueOnce(COMPLETE);
    const deps = makeDeps({ poll });
    const signIn = createCodexDeviceSignIn(deps);

    await signIn.begin();
    signIn.openVerificationPage();
    expect(deps.openWindow).toHaveBeenCalledWith("https://auth.openai.com/codex/device");

    await vi.advanceTimersByTimeAsync(5000);
    expect(deps.onSignedIn).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(5000);

    expect(deps.onSignedIn).toHaveBeenCalledWith({
      config: COMPLETE.config,
      accountId: "acct-1",
    });
    expect(deps.popup.close).toHaveBeenCalled();
    expect(signIn.phase.value).toBe("idle");
    expect(signIn.userCode.value).toBe("");
    await vi.advanceTimersByTimeAsync(20000);
    expect(poll).toHaveBeenCalledTimes(2);
  });

  it("stops with the server's message on a 4xx", async () => {
    const deps = makeDeps({
      poll: vi.fn(async () => {
        throw httpError(400, "The sign-in code expired; start the ChatGPT sign-in again");
      }),
    });
    const signIn = createCodexDeviceSignIn(deps);

    await signIn.begin();
    await vi.advanceTimersByTimeAsync(5000);

    expect(signIn.phase.value).toBe("idle");
    expect(signIn.error.value).toContain("expired");
    await vi.advanceTimersByTimeAsync(20000);
    expect(deps.poll).toHaveBeenCalledTimes(1);
  });

  it("retries transient failures, then gives up", async () => {
    const deps = makeDeps({
      poll: vi.fn(async () => {
        throw new Error("Network Error");
      }),
    });
    const signIn = createCodexDeviceSignIn(deps);

    await signIn.begin();
    await vi.advanceTimersByTimeAsync(10000);
    expect(signIn.phase.value).toBe("waiting");
    await vi.advanceTimersByTimeAsync(5000);

    expect(deps.poll).toHaveBeenCalledTimes(3);
    expect(signIn.phase.value).toBe("idle");
    expect(signIn.error.value).toBe("ChatGPT sign-in failed. Start the sign-in again.");
  });

  it("gives up locally once the code has expired", async () => {
    const deps = makeDeps({
      start: vi.fn(async () => ({
        ...START,
        expires_at: new Date(Date.now() + 7000).toISOString(),
      })),
    });
    const signIn = createCodexDeviceSignIn(deps);

    await signIn.begin();
    await vi.advanceTimersByTimeAsync(10000);

    expect(deps.poll).toHaveBeenCalledTimes(1);
    expect(signIn.error.value).toContain("expired");
    expect(signIn.phase.value).toBe("idle");
  });

  it("ignores a poll answer that lands after cancel", async () => {
    let resolvePoll: (value: CodexDeviceSignInPoll) => void = () => {};
    const deps = makeDeps({
      poll: vi.fn(
        () =>
          new Promise<CodexDeviceSignInPoll>((resolve) => {
            resolvePoll = resolve;
          }),
      ),
    });
    const signIn = createCodexDeviceSignIn(deps);

    await signIn.begin();
    await vi.advanceTimersByTimeAsync(5000);
    signIn.cancel();
    resolvePoll(COMPLETE);
    await vi.advanceTimersByTimeAsync(0);

    expect(deps.onSignedIn).not.toHaveBeenCalled();
    expect(signIn.phase.value).toBe("idle");
  });

  it("shows why the code could not be fetched", async () => {
    const deps = makeDeps({
      start: vi.fn(async () => {
        throw httpError(502, "OpenAI does not offer device code sign-in right now");
      }),
    });
    const signIn = createCodexDeviceSignIn(deps);

    await signIn.begin();

    expect(signIn.phase.value).toBe("idle");
    expect(signIn.error.value).toContain("device code sign-in");
    expect(deps.poll).not.toHaveBeenCalled();
  });

  it("stops polling on dispose", async () => {
    const deps = makeDeps();
    const signIn = createCodexDeviceSignIn(deps);

    await signIn.begin();
    signIn.dispose();
    await vi.advanceTimersByTimeAsync(20000);

    expect(deps.poll).not.toHaveBeenCalled();
  });
});
