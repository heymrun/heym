import { describe, expect, it } from "vitest";

import { acceptAttribute, fileRejection, isFileTypeAllowed } from "@/lib/fileAccept";

const pdf = { name: "Invoice.PDF", type: "application/pdf", size: 2 * 1024 * 1024 };

describe("isFileTypeAllowed", () => {
  it("matches MIME types, MIME globs and extensions like the server", () => {
    expect(isFileTypeAllowed(pdf, ["application/pdf"])).toBe(true);
    expect(isFileTypeAllowed(pdf, ["application/*"])).toBe(true);
    expect(isFileTypeAllowed(pdf, [".pdf"])).toBe(true);
    expect(isFileTypeAllowed(pdf, ["image/*", ".csv"])).toBe(false);
    expect(isFileTypeAllowed(pdf, ["*/*"])).toBe(true);
    expect(isFileTypeAllowed(pdf, ["application/pd?"])).toBe(true);
    expect(isFileTypeAllowed(pdf, [])).toBe(true);
  });
});

describe("fileRejection", () => {
  it("names the reason a file cannot be dropped", () => {
    expect(fileRejection(pdf, [], 5)).toBeNull();
    expect(fileRejection(pdf, ["image/*"], 5)).toBe("This workflow takes image/* files.");
    expect(fileRejection(pdf, [], 1)).toBe("The file is larger than 1 MB.");
  });

  it("builds the picker's accept attribute", () => {
    expect(acceptAttribute(["image/*", ".csv"])).toBe("image/*,.csv");
    expect(acceptAttribute([])).toBeUndefined();
  });
});
