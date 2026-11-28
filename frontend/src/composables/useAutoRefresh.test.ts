import { describe, expect, it } from "vitest";

import {
  formatCountdown,
  parseAutoRefreshSecondsInput,
  validateAutoRefreshSeconds,
} from "./useAutoRefresh";

describe("parseAutoRefreshSecondsInput", () => {
  it("preserves decimal input so validation can reject it", () => {
    const parsed = parseAutoRefreshSecondsInput("10.5");

    expect(parsed).toBe(10.5);
    expect(validateAutoRefreshSeconds(parsed)).toBe("Enter a whole number of seconds");
  });

  it("parses whole-number input", () => {
    expect(parseAutoRefreshSecondsInput("120")).toBe(120);
  });

  it("rejects empty input as a non-finite value", () => {
    expect(parseAutoRefreshSecondsInput("")).toBeNaN();
  });
});

describe("validateAutoRefreshSeconds", () => {
  it("accepts a whole number within the default bounds", () => {
    expect(validateAutoRefreshSeconds(30)).toBeNull();
  });

  it("accepts exactly the minimum bound", () => {
    expect(validateAutoRefreshSeconds(10)).toBeNull();
  });

  it("accepts exactly the maximum bound", () => {
    expect(validateAutoRefreshSeconds(3600)).toBeNull();
  });

  it("rejects one less than the minimum bound", () => {
    expect(validateAutoRefreshSeconds(9)).toBe("Minimum interval is 10s");
  });

  it("rejects one more than the maximum bound", () => {
    expect(validateAutoRefreshSeconds(3601)).toBe("Maximum interval is 3600s");
  });

  it("respects custom bounds instead of the defaults", () => {
    expect(validateAutoRefreshSeconds(5, { minSeconds: 5, maxSeconds: 20 })).toBeNull();
    expect(validateAutoRefreshSeconds(4, { minSeconds: 5, maxSeconds: 20 })).toBe(
      "Minimum interval is 5s",
    );
    expect(validateAutoRefreshSeconds(21, { minSeconds: 5, maxSeconds: 20 })).toBe(
      "Maximum interval is 20s",
    );
  });

  it("rejects non-finite values", () => {
    expect(validateAutoRefreshSeconds(NaN)).toBe("Enter a whole number of seconds");
    expect(validateAutoRefreshSeconds(Infinity)).toBe("Enter a whole number of seconds");
    expect(validateAutoRefreshSeconds(-Infinity)).toBe("Enter a whole number of seconds");
  });

  it("rejects a finite non-integer value", () => {
    expect(validateAutoRefreshSeconds(30.5)).toBe("Enter a whole number of seconds");
  });

  it("reports the whole-number error before the minimum-bound error when both apply", () => {
    // 5.5 is both non-integer and below the default minimum of 10 seconds; the
    // whole-number check runs first and must win.
    expect(validateAutoRefreshSeconds(5.5)).toBe("Enter a whole number of seconds");
  });
});

describe("formatCountdown", () => {
  it("formats non-compact as m:ss, zero-padding single-digit seconds", () => {
    expect(formatCountdown(65)).toBe("1:05");
  });

  it("formats an exact minute with zero seconds", () => {
    expect(formatCountdown(60)).toBe("1:00");
  });

  it("ignores compact mode once a full minute has elapsed", () => {
    expect(formatCountdown(60, true)).toBe("1:00");
  });

  it("switches to the compact seconds-only form under a minute when compact is true", () => {
    expect(formatCountdown(59, true)).toBe("59s");
  });

  it("does not use the compact form under a minute when compact is false", () => {
    expect(formatCountdown(59, false)).toBe("0:59");
    expect(formatCountdown(59)).toBe("0:59");
  });
});
