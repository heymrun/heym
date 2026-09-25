import { describe, expect, it } from "vitest";

import { getOutputImageSrcs, maskImageDataForDisplay } from "@/lib/executionImages";

const shotA = "A".repeat(120);
const shotB = "B".repeat(120);
const shotC = "C".repeat(120);

describe("getOutputImageSrcs", () => {
  it("keeps Playwright screenshots in step order when the last one repeats as `screenshot`", () => {
    const output = {
      status: "ok",
      results: { first: shotA, title: "Example page", second: shotB, third: shotC },
      screenshot: shotC,
    };

    expect(getOutputImageSrcs(output)).toEqual([
      `data:image/png;base64,${shotA}`,
      `data:image/png;base64,${shotB}`,
      `data:image/png;base64,${shotC}`,
    ]);
  });

  it("returns nothing for outputs without images", () => {
    expect(getOutputImageSrcs({ text: "hello" })).toEqual([]);
    expect(getOutputImageSrcs(null)).toEqual([]);
  });
});

describe("maskImageDataForDisplay", () => {
  it("shortens inline image data and leaves other values intact", () => {
    const dataUrl = `data:image/png;base64,${shotA}`;

    expect(
      maskImageDataForDisplay({
        results: { value: shotA, title: "Example page" },
        image: dataUrl,
        items: [shotB, 3],
      }),
    ).toEqual({
      results: { value: "[Base64 data]", title: "Example page" },
      image: `${dataUrl.slice(0, 150)}...`,
      items: ["[Base64 data]", 3],
    });
  });
});
