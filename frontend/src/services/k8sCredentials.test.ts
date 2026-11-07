import { afterEach, describe, expect, it, vi } from "vitest";

import api from "@/services/api";
import { k8sCredentialsEnabled } from "@/services/k8sCredentials";

describe("k8sCredentialsEnabled", () => {
  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("follows the backend's enabled flag", async () => {
    const get = vi.spyOn(api, "get");
    get.mockResolvedValueOnce({ data: { enabled: false, synced: false, credentials: [] } });
    expect(await k8sCredentialsEnabled()).toBe(false);

    get.mockResolvedValueOnce({ data: { enabled: true, synced: true, credentials: [] } });
    expect(await k8sCredentialsEnabled()).toBe(true);
    expect(get).toHaveBeenCalledWith("/admin/k8s-credentials");
  });

  it("treats a failed request as off", async () => {
    vi.spyOn(api, "get").mockRejectedValueOnce(new Error("403"));
    expect(await k8sCredentialsEnabled()).toBe(false);
  });
});
