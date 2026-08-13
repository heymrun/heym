import { describe, expect, it } from "vitest";

import { adjacentImageSrc, imageGalleryPosition } from "@/lib/imageLightboxGallery";

const gallery = ["a", "b", "c"];

describe("adjacentImageSrc", () => {
  it("wraps within the same gallery", () => {
    expect(adjacentImageSrc(gallery, "a", 1)).toBe("b");
    expect(adjacentImageSrc(gallery, "c", 1)).toBe("a");
    expect(adjacentImageSrc(gallery, "a", -1)).toBe("c");
  });

  it("does not leave a one-image gallery", () => {
    expect(adjacentImageSrc(["only"], "only", 1)).toBe("only");
    expect(adjacentImageSrc(["only"], "only", -1)).toBe("only");
  });

  it("ignores a current src that is not in the gallery", () => {
    expect(adjacentImageSrc(gallery, "other", 1)).toBe("other");
  });
});

describe("imageGalleryPosition", () => {
  it("returns a 1-based counter for multi-image galleries", () => {
    expect(imageGalleryPosition(gallery, "b")).toEqual({ index: 2, total: 3 });
  });

  it("hides the counter for a single image", () => {
    expect(imageGalleryPosition(["only"], "only")).toBeNull();
  });
});
