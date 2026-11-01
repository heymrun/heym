import { beforeEach, describe, expect, it, vi } from "vitest";

import { ATTACHMENT_ACCEPT, toAttachmentPayload, useFileAttachment } from "./useFileAttachment";

// `File`/`Blob` are native globals in this Node version (v24) - no jsdom
// needed, construct real `new File([...], name, {type})` instances directly.
// `FileReader` is NOT native in Node though, and readFileAsText/
// readFileAsDataURL both call `new FileReader()` - but only lazily, inside
// processFile, not at the source module's own top level. That means (unlike
// useTextToSpeech's Audio gotcha) a plain vi.stubGlobal("FileReader", ...) in
// beforeEach is enough here, no vi.hoisted() hoisting trick required, since
// nothing reads the global before the test itself calls processFile.

class FakeFileReader {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  result: string | null = null;
  readAsText(file: File) {
    file.text().then((text) => {
      this.result = text;
      this.onload?.();
    });
  }
  readAsDataURL(file: File) {
    file.arrayBuffer().then((buf) => {
      const b64 = Buffer.from(buf).toString("base64");
      this.result = `data:${file.type};base64,${b64}`;
      this.onload?.();
    });
  }
}

class FakeFailingFileReader {
  onload: (() => void) | null = null;
  onerror: (() => void) | null = null;
  result: string | null = null;
  readAsText() {
    Promise.resolve().then(() => this.onerror?.());
  }
  readAsDataURL() {
    Promise.resolve().then(() => this.onerror?.());
  }
}

const uploadMock = vi.fn();
const chatFiles = { upload: uploadMock };

beforeEach(() => {
  vi.stubGlobal("FileReader", FakeFileReader);
  uploadMock.mockReset();
});

function storedFile(name: string, size: number, mime: string): Record<string, unknown> {
  return { id: "file-1", name, size, mime };
}

describe("processFile - documents go to Drive", () => {
  it("uploads a spreadsheet and keeps only its Drive reference", async () => {
    uploadMock.mockResolvedValue(storedFile("q3.xlsx", 4096, "application/vnd.ms-excel"));
    const file = new File([new Uint8Array(10)], "q3.xlsx", { type: "" });

    const { processFile, attachedFile, attachmentError } = useFileAttachment(chatFiles);
    await processFile(file);

    expect(attachmentError.value).toBeNull();
    expect(uploadMock).toHaveBeenCalledWith(file);
    expect(attachedFile.value).toEqual({
      name: "q3.xlsx",
      kind: "file",
      mimeType: "application/vnd.ms-excel",
      content: "",
      sizeKb: 4,
      fileId: "file-1",
    });
  });

  it("sends PDFs to Drive instead of extracting their text in the browser", async () => {
    uploadMock.mockResolvedValue(storedFile("doc.pdf", 2048, "application/pdf"));
    const file = new File(["%PDF"], "notes.txt", { type: "application/pdf" });

    const { processFile, attachedFile } = useFileAttachment(chatFiles);
    await processFile(file);

    expect(attachedFile.value?.kind).toBe("file");
    expect(attachedFile.value?.content).toBe("");
  });

  it("shows the server's reason when Drive refuses the upload", async () => {
    uploadMock.mockRejectedValue(new Error("File size exceeds limit (100 MB)"));
    const file = new File(["a,b"], "big.csv", { type: "text/csv" });

    const { processFile, attachmentError, attachedFile } = useFileAttachment(chatFiles);
    await processFile(file);

    expect(attachmentError.value).toBe("File size exceeds limit (100 MB)");
    expect(attachedFile.value).toBeNull();
  });

  it("refuses documents when the host has no upload port", async () => {
    const file = new File(["a,b"], "data.csv", { type: "text/csv" });

    const { processFile, attachmentError } = useFileAttachment(null);
    await processFile(file);

    expect(attachmentError.value).toBe("Unsupported file type");
  });

  it("builds a request payload with the file id and no content", () => {
    const payload = toAttachmentPayload({
      name: "q3.xlsx",
      kind: "file",
      mimeType: "",
      content: "",
      sizeKb: 1,
      fileId: "file-1",
    });
    expect(payload).toEqual({ name: "q3.xlsx", kind: "file", content: "", file_id: "file-1" });
  });

  it("accepts the document types in the file picker", () => {
    for (const ext of [".xlsx", ".xls", ".docx", ".pdf", ".csv", ".tsv", ".json"]) {
      expect(ATTACHMENT_ACCEPT.split(",")).toContain(ext);
    }
  });
});

describe("processFile - zip", () => {
  it("keeps a zip as a data URL so the server can unpack it", async () => {
    const { processFile, attachedFile, attachmentError } = useFileAttachment(null);
    const file = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], "skill.zip", {
      type: "application/zip",
    });

    await processFile(file);

    expect(attachmentError.value).toBeNull();
    expect(attachedFile.value?.kind).toBe("zip");
    expect(attachedFile.value?.content.startsWith("data:")).toBe(true);
    expect(uploadMock).not.toHaveBeenCalled();
  });
});

describe("processFile - unsupported/oversized files", () => {
  it("sets an error for an unsupported file type, without reading it", async () => {
    const FileReaderSpy = vi.fn();
    vi.stubGlobal("FileReader", FileReaderSpy);

    const { processFile, attachmentError, attachedFile } = useFileAttachment(null);
    const file = new File(["x"], "x.exe", { type: "application/octet-stream" });

    await processFile(file);

    expect(attachmentError.value).toBe("Unsupported file type");
    expect(attachedFile.value).toBeNull();
    expect(FileReaderSpy).not.toHaveBeenCalled();
  });

  it("rejects an inline text file over the text size limit", async () => {
    const MAX_TEXT_BYTES = 500 * 1024;
    const FileReaderSpy = vi.fn();
    vi.stubGlobal("FileReader", FileReaderSpy);
    const oversized = new File(["a".repeat(MAX_TEXT_BYTES + 1)], "server.log", {
      type: "text/plain",
    });

    const { processFile, attachmentError, attachedFile } = useFileAttachment(null);
    await processFile(oversized);

    expect(attachmentError.value).toContain("File too large");
    expect(attachedFile.value).toBeNull();
    expect(FileReaderSpy).not.toHaveBeenCalled();
  });

  it("rejects an image file over the image size limit", async () => {
    const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
    const FileReaderSpy = vi.fn();
    vi.stubGlobal("FileReader", FileReaderSpy);
    const oversized = new File([new Uint8Array(MAX_IMAGE_BYTES + 1)], "photo.png", {
      type: "image/png",
    });

    const { processFile, attachmentError, attachedFile } = useFileAttachment(null);
    await processFile(oversized);

    expect(attachmentError.value).toContain("File too large");
    expect(attachedFile.value).toBeNull();
    expect(FileReaderSpy).not.toHaveBeenCalled();
  });
});

describe("processFile - inline text files", () => {
  it("reads a code file's content and populates attachedFile with correct metadata", async () => {
    const file = new File(["print('hi')"], "script.py", { type: "text/x-python" });

    const { processFile, attachedFile } = useFileAttachment(null);
    await processFile(file);

    expect(attachedFile.value).toEqual({
      name: "script.py",
      kind: "text",
      mimeType: "text/x-python",
      content: "print('hi')",
      sizeKb: Math.round(file.size / 1024),
    });
  });

  it("truncates text content longer than MAX_CONTENT_CHARS", async () => {
    const MAX_CONTENT_CHARS = 100_000;
    const longText = "a".repeat(MAX_CONTENT_CHARS + 50);
    const file = new File([longText], "server.log", { type: "text/plain" });

    const { processFile, attachedFile } = useFileAttachment(null);
    await processFile(file);

    expect(attachedFile.value?.content.length).toBe(MAX_CONTENT_CHARS);
  });

  it("sets a generic error message when reading a text file fails", async () => {
    vi.stubGlobal("FileReader", FakeFailingFileReader);
    const file = new File(["hello"], "server.log", { type: "text/plain" });

    const { processFile, attachmentError, attachedFile } = useFileAttachment(null);
    await processFile(file);

    expect(attachmentError.value).toBe("Failed to read file");
    expect(attachedFile.value).toBeNull();
  });
});

describe("processFile - image files", () => {
  it("reads an image file as a data URL", async () => {
    const file = new File([new Uint8Array([1, 2, 3])], "photo.png", { type: "image/png" });

    const { processFile, attachedFile } = useFileAttachment(null);
    await processFile(file);

    expect(attachedFile.value?.content.startsWith("data:image/png;base64,")).toBe(true);
  });
});
