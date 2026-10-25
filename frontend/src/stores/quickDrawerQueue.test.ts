import { describe, expect, it } from "vitest";

import { normalizeRunStatus, queueLabel } from "@/stores/quickDrawerQueue";

describe("queueLabel", () => {
  it("reads like the history badge", () => {
    expect(queueLabel({ execution_id: "e", position: 2, size: 5, running: 1, limit: 1 })).toBe(
      "Waiting in queue (2/5)",
    );
  });
});

describe("normalizeRunStatus", () => {
  it("maps a run that never executed to error", () => {
    expect(normalizeRunStatus("expired")).toBe("error");
    expect(normalizeRunStatus("cancelled")).toBe("error");
    expect(normalizeRunStatus("queue_full")).toBe("error");
  });

  it("keeps the statuses the drawer already knows", () => {
    expect(normalizeRunStatus("success")).toBe("success");
    expect(normalizeRunStatus("error")).toBe("error");
    expect(normalizeRunStatus("pending")).toBe("pending");
    expect(normalizeRunStatus("awaiting_file_upload")).toBe("pending");
  });
});
