import { describe, expect, it } from "vitest";

import { getOutputImageSrcs, maskImageDataForDisplay } from "@/lib/executionImages";

const PNG = "iVBORw0KGgoAAAANSUhEUg";
const shotA = `${PNG}${"A".repeat(120)}`;
const shotB = `${PNG}${"B".repeat(120)}`;
const shotC = `${PNG}${"C".repeat(120)}`;
const jpeg = `/9j/4AAQSkZJRgABAQ${"D".repeat(120)}`;
const svg = btoa(`<svg xmlns="http://www.w3.org/2000/svg">${" ".repeat(90)}</svg>`);

describe("getOutputImageSrcs", () => {
  it("finds base64 images anywhere in an output and names their type from the bytes", () => {
    const shot = { filename: "shot-1.jpg", label: "Screenshot 1 of 1", data: jpeg };
    const output = { headers: {}, body: { message: "Broken table", screenshots: [shot] }, screenshots: [shot] };

    expect(getOutputImageSrcs(output)).toEqual([`data:image/jpeg;base64,${jpeg}`]);
  });

  it("takes the type from a sibling MIME value when the bytes do not tell it", () => {
    expect(getOutputImageSrcs({ file_base64: svg, mime_type: "image/svg+xml" })).toEqual([
      `data:image/svg+xml;base64,${svg}`,
    ]);
  });

  it("leaves long base64 that is not an image alone", () => {
    expect(getOutputImageSrcs({ token: "A".repeat(200), file: { data: btoa("x".repeat(120)) } })).toEqual([]);
  });

  it("keeps data URLs and image URLs", () => {
    const dataUrl = `data:image/png;base64,${shotA}`;

    expect(getOutputImageSrcs({ image: "https://cdn.example/cat.png", nested: [{ preview: dataUrl }] })).toEqual([
      "https://cdn.example/cat.png",
      dataUrl,
    ]);
  });

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
