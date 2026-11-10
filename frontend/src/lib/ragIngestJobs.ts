import { onScopeDispose, ref, type Ref } from "vue";

import type { RagIngestJob } from "@/types/ragIngest";

export const INGEST_POLL_MS = 4000;

export interface IngestJobPolling {
  jobs: Ref<RagIngestJob[]>;
  /** Loads the jobs now, and again every few seconds while one is queued or processing. */
  refresh: () => Promise<void>;
}

export function isActiveIngestJob(job: RagIngestJob): boolean {
  return job.status !== "failed";
}

/**
 * A store's background uploads, polled while one runs. A job that was running and is gone has
 * its chunks in the store, so `onFinished` is called to reload the documents. API-free: Heym
 * and Work pass their own `load`.
 */
export function useIngestJobPolling(
  load: () => Promise<RagIngestJob[]>,
  onFinished: () => void,
  intervalMs: number = INGEST_POLL_MS,
): IngestJobPolling {
  const jobs = ref<RagIngestJob[]>([]);
  let timer: ReturnType<typeof setTimeout> | null = null;
  let disposed = false;

  async function refresh(): Promise<void> {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    const running = jobs.value.filter(isActiveIngestJob).map((job) => job.id);
    let next: RagIngestJob[];
    try {
      next = await load();
    } catch {
      return;
    }
    if (disposed) return;
    jobs.value = next;
    const present = new Set(next.map((job) => job.id));
    if (running.some((id) => !present.has(id))) onFinished();
    if (next.some(isActiveIngestJob)) {
      timer = setTimeout(() => void refresh(), intervalMs);
    }
  }

  onScopeDispose(() => {
    disposed = true;
    if (timer !== null) clearTimeout(timer);
  });

  return { jobs, refresh };
}
