import { describe, expect, it } from "vitest";

import { activeExecutionStatus } from "@/components/Panels/activeExecutionStatus";

describe("activeExecutionStatus", () => {
  it("labels a queued run with its position", () => {
    expect(activeExecutionStatus({ status: "queued", queue_position: 2, queue_size: 5 })).toEqual({
      kind: "queued",
      label: "Queued 2/5",
      canOpenLive: false,
    });
  });

  it("keeps running runs live", () => {
    expect(activeExecutionStatus({ status: "running" })).toEqual({
      kind: "running",
      label: "Running",
      canOpenLive: true,
    });
  });

  it("treats a missing status as running", () => {
    expect(activeExecutionStatus({}).kind).toBe("running");
  });
});
