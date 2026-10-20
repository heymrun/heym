import { describe, expect, it } from "vitest";

import { portalDeleteWarning } from "@/lib/portalDeleteWarning";

describe("portalDeleteWarning", () => {
  it("warns when the last user of an enabled portal is deleted", () => {
    const warning = portalDeleteWarning({ isLastUser: true, portalEnabled: true });
    expect(warning).toContain("publicly accessible");
    expect(warning).toContain("without logging in");
  });

  it("warns when the portal state is unknown", () => {
    const warning = portalDeleteWarning({ isLastUser: true, portalEnabled: null });
    expect(warning).toContain("publicly accessible");
  });

  it("does not warn when other portal users remain", () => {
    expect(portalDeleteWarning({ isLastUser: false, portalEnabled: true })).toBeNull();
  });

  it("does not warn when the portal is disabled", () => {
    expect(portalDeleteWarning({ isLastUser: true, portalEnabled: false })).toBeNull();
  });
});
