import { describe, expect, it } from "vitest";

import { RAG_FORMATS_LINE, ragFileKind } from "@/lib/ragFileTypes";

function file(name: string, body: BlobPart = "x"): File {
  return new File([body], name);
}

describe("ragFileKind", () => {
  it("knows documents, images and audio by extension, in any case", async () => {
    expect(await ragFileKind(file("a.PDF", new Uint8Array([0])))).toBe("document");
    expect(await ragFileKind(file(".md"))).toBe("document");
    expect(await ragFileKind(file("scan.JPEG", new Uint8Array([0])))).toBe("image");
    expect(await ragFileKind(file("call.flac", new Uint8Array([0])))).toBe("audio");
  });

  it("takes a UTF-8 file of any name as text", async () => {
    expect(await ragFileKind(file("burak.akgun", "4 rfc ve pr\n5 açık issue\n"))).toBe("text");
    expect(await ragFileKind(file("README", "# hi"))).toBe("text");
  });

  it("refuses binary files it does not know", async () => {
    expect(await ragFileKind(file("report.docx", new Uint8Array([0x50, 0x4b, 0, 0])))).toBeNull();
  });

  it("names the formats in one line", () => {
    expect(RAG_FORMATS_LINE).toContain("audio (mp3, wav, ogg, flac)");
  });
});
