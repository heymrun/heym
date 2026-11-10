import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { effectScope } from "vue";

import type { RagIngestJob } from "@/types/ragIngest";

import { useIngestJobPolling } from "@/lib/ragIngestJobs";

function job(id: string, status: RagIngestJob["status"]): RagIngestJob {
  return { id, filename: `${id}.mp3`, file_size: 1, kind: "audio", status, error: null, created_at: "", updated_at: "" };
}

beforeEach(() => vi.useFakeTimers());
afterEach(() => vi.useRealTimers());

describe("useIngestJobPolling", () => {
  it("polls while a job runs and reports when it is gone", async () => {
    const load = vi.fn()
      .mockResolvedValueOnce([job("a", "processing")])
      .mockResolvedValueOnce([job("a", "processing")])
      .mockResolvedValueOnce([]);
    const finished = vi.fn();
    const scope = effectScope();
    const polling = scope.run(() => useIngestJobPolling(load, finished, 1000))!;

    await polling.refresh();
    expect(polling.jobs.value).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1000);
    expect(finished).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(1000);
    expect(finished).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(5000);
    expect(load).toHaveBeenCalledTimes(3);
    scope.stop();
  });

  it("does not poll when only failed jobs are left", async () => {
    const load = vi.fn().mockResolvedValue([job("a", "failed")]);
    const scope = effectScope();
    const polling = scope.run(() => useIngestJobPolling(load, vi.fn(), 1000))!;

    await polling.refresh();
    await vi.advanceTimersByTimeAsync(5000);
    expect(load).toHaveBeenCalledTimes(1);
    scope.stop();
  });

  it("keeps the last jobs when a load fails", async () => {
    const load = vi.fn().mockResolvedValueOnce([job("a", "failed")]).mockRejectedValueOnce(new Error("down"));
    const scope = effectScope();
    const polling = scope.run(() => useIngestJobPolling(load, vi.fn(), 1000))!;

    await polling.refresh();
    await polling.refresh();
    expect(polling.jobs.value.map((item) => item.id)).toEqual(["a"]);
    scope.stop();
  });

  it("stops polling when its scope ends", async () => {
    const load = vi.fn().mockResolvedValue([job("a", "queued")]);
    const scope = effectScope();
    const polling = scope.run(() => useIngestJobPolling(load, vi.fn(), 1000))!;

    await polling.refresh();
    scope.stop();
    await vi.advanceTimersByTimeAsync(5000);
    expect(load).toHaveBeenCalledTimes(1);
  });
});
