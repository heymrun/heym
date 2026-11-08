import { beforeEach, describe, expect, it, vi } from "vitest";

import { readFileForInputField } from "./inputFieldFile";

// FileReader is not native in Node; the reader only needs readAsText and readAsDataURL.
class FakeFileReader {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  result: string | null = null;
  readAsText(file: File): void {
    void file.text().then((text) => {
      this.result = text;
      this.onload?.();
    });
  }
  readAsDataURL(file: File): void {
    void file.arrayBuffer().then((buf) => {
      this.result = `data:${file.type};base64,${Buffer.from(buf).toString("base64")}`;
      this.onload?.();
    });
  }
}

beforeEach(() => {
  vi.stubGlobal("FileReader", FakeFileReader);
});

describe("readFileForInputField", () => {
  it("reads a UTF-8 file with an unknown extension as text", async () => {
    const file = new File(["4 rfc ve pr\n\n5 açık issue\n"], "burak.akgun", { type: "" });

    await expect(readFileForInputField(file)).resolves.toEqual({
      content: "4 rfc ve pr\n\n5 açık issue\n",
      name: "burak.akgun",
      kind: "text",
    });
  });

  it("reads a UTF-8 file without an extension as text", async () => {
    const file = new File(["all: build\n"], "Makefile", { type: "" });

    await expect(readFileForInputField(file)).resolves.toMatchObject({ kind: "text" });
  });

  it("still refuses a binary file", async () => {
    const file = new File([new Uint8Array([0x4d, 0x5a, 0x00, 0x90])], "tool.exe", {
      type: "application/octet-stream",
    });

    await expect(readFileForInputField(file)).rejects.toThrow("Unsupported file type");
  });

  it("keeps the text size limit for a sniffed file", async () => {
    const file = new File(["a".repeat(500 * 1024 + 1)], "big.notes", { type: "" });

    await expect(readFileForInputField(file)).rejects.toThrow("File too large");
  });

  it("reads an image as a data URL", async () => {
    const file = new File([new Uint8Array([1, 2, 3])], "photo.png", { type: "image/png" });

    const result = await readFileForInputField(file);

    expect(result.kind).toBe("image");
    expect(result.content.startsWith("data:image/png;base64,")).toBe(true);
  });
});
