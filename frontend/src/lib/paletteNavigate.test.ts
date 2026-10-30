import { describe, expect, it } from "vitest";

import { isOpenInNewTab } from "@/lib/paletteNavigate";

describe("isOpenInNewTab", () => {
  it("opens in a new tab on Ctrl+click or Cmd+click", () => {
    expect(isOpenInNewTab({ ctrlKey: true, metaKey: false } as MouseEvent)).toBe(true);
    expect(isOpenInNewTab({ ctrlKey: false, metaKey: true } as MouseEvent)).toBe(true);
  });

  it("stays in the current tab for a plain click", () => {
    expect(isOpenInNewTab({ ctrlKey: false, metaKey: false } as MouseEvent)).toBe(false);
  });

  it("treats a missing event as a plain click", () => {
    expect(isOpenInNewTab(undefined)).toBe(false);
    expect(isOpenInNewTab(null)).toBe(false);
  });
});
