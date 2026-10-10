import { beforeEach, describe, expect, it, vi } from "vitest";

import { useFileAttachment } from "./useFileAttachment";

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

beforeEach(() => {
  vi.stubGlobal("FileReader", FakeFileReader);
});

const { getDocumentMock } = vi.hoisted(() => ({ getDocumentMock: vi.fn() }));

vi.mock("pdfjs-dist", () => ({
  getDocument: getDocumentMock,
  GlobalWorkerOptions: { workerSrc: "" },
}));

function mockPdf(pagesText: string[]) {
  getDocumentMock.mockReturnValue({
    promise: Promise.resolve({
      numPages: pagesText.length,
      getPage: (i: number) =>
        Promise.resolve({
          getTextContent: () => Promise.resolve({ items: [{ str: pagesText[i - 1] }] }),
        }),
    }),
  });
}

describe("processFile - zip", () => {
  it("keeps a zip as a data URL so the server can unpack it", async () => {
    const { processFile, attachedFile, attachmentError } = useFileAttachment();
    const file = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], "skill.zip", {
      type: "application/zip",
    });

    await processFile(file);

    expect(attachmentError.value).toBeNull();
    expect(attachedFile.value?.kind).toBe("zip");
    expect(attachedFile.value?.content.startsWith("data:")).toBe(true);
  });
});

describe("processFile - unsupported/oversized files", () => {
  it("sets an error for an unsupported file type, without reading it", async () => {
    const FileReaderSpy = vi.fn();
    vi.stubGlobal("FileReader", FileReaderSpy);

    const { processFile, attachmentError, attachedFile } = useFileAttachment();
    const file = new File(["x"], "x.exe", { type: "application/octet-stream" });

    await processFile(file);

    expect(attachmentError.value).toBe("Unsupported file type");
    expect(attachedFile.value).toBeNull();
    expect(FileReaderSpy).not.toHaveBeenCalled();
  });

  it("rejects a text file over the text size limit", async () => {
    const MAX_TEXT_BYTES = 500 * 1024;
    const FileReaderSpy = vi.fn();
    vi.stubGlobal("FileReader", FileReaderSpy);
    const oversized = new File(["a".repeat(MAX_TEXT_BYTES + 1)], "notes.txt", {
      type: "text/plain",
    });

    const { processFile, attachmentError, attachedFile } = useFileAttachment();
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

    const { processFile, attachmentError, attachedFile } = useFileAttachment();
    await processFile(oversized);

    expect(attachmentError.value).toContain("File too large");
    expect(attachedFile.value).toBeNull();
    expect(FileReaderSpy).not.toHaveBeenCalled();
  });

  it("rejects a pdf file over the pdf size limit", async () => {
    const MAX_PDF_BYTES = 5 * 1024 * 1024;
    const oversized = new File([new Uint8Array(MAX_PDF_BYTES + 1)], "file.pdf", {
      type: "application/pdf",
    });

    const { processFile, attachmentError, attachedFile } = useFileAttachment();
    await processFile(oversized);

    expect(attachmentError.value).toContain("File too large");
    expect(attachedFile.value).toBeNull();
    expect(getDocumentMock).not.toHaveBeenCalled();
  });
});

describe("processFile - detectKind priority", () => {
  it("an application/pdf mime type is detected as pdf regardless of extension", async () => {
    mockPdf(["text"]);
    const file = new File(["ignored"], "notes.txt", { type: "application/pdf" });

    const { processFile, attachedFile } = useFileAttachment();
    await processFile(file);

    expect(attachedFile.value?.kind).toBe("pdf");
  });

  it("a recognized image mime type is detected as image", async () => {
    const file = new File(["abc"], "blob", { type: "image/png" });

    const { processFile, attachedFile } = useFileAttachment();
    await processFile(file);

    expect(attachedFile.value?.kind).toBe("image");
  });

  it("falls back to extension-based detection for text files", async () => {
    const file = new File(["hello"], "notes.txt", { type: "" });

    const { processFile, attachedFile } = useFileAttachment();
    await processFile(file);

    expect(attachedFile.value?.kind).toBe("text");
  });
});

describe("processFile - text files", () => {
  it("reads a text file's content and populates attachedFile with correct metadata", async () => {
    const file = new File(["hello world"], "notes.txt", { type: "text/plain" });

    const { processFile, attachedFile } = useFileAttachment();
    await processFile(file);

    expect(attachedFile.value).toEqual({
      name: "notes.txt",
      kind: "text",
      mimeType: "text/plain",
      content: "hello world",
      sizeKb: Math.round(file.size / 1024),
    });
  });

  it("truncates text content longer than MAX_CONTENT_CHARS", async () => {
    const MAX_CONTENT_CHARS = 100_000;
    const longText = "a".repeat(MAX_CONTENT_CHARS + 50);
    const file = new File([longText], "notes.txt", { type: "text/plain" });

    const { processFile, attachedFile } = useFileAttachment();
    await processFile(file);

    expect(attachedFile.value?.content.length).toBe(MAX_CONTENT_CHARS);
    expect(attachedFile.value?.content).toBe(longText.slice(0, MAX_CONTENT_CHARS));
  });
});

describe("processFile - image files", () => {
  it("reads an image file as a data URL", async () => {
    const file = new File([new Uint8Array([1, 2, 3])], "photo.png", { type: "image/png" });

    const { processFile, attachedFile } = useFileAttachment();
    await processFile(file);

    expect(attachedFile.value?.content.startsWith("data:image/png;base64,")).toBe(true);
  });
});

describe("processFile - pdf files", () => {
  it("extracts and joins text across all pdf pages", async () => {
    mockPdf(["Page 1 text", "Page 2 text"]);
    const file = new File(["ignored"], "doc.pdf", { type: "application/pdf" });

    const { processFile, attachedFile } = useFileAttachment();
    await processFile(file);

    expect(attachedFile.value?.content).toBe("Page 1 text\nPage 2 text");
  });

  it("truncates pdf content longer than MAX_CONTENT_CHARS", async () => {
    const MAX_CONTENT_CHARS = 100_000;
    mockPdf(["a".repeat(MAX_CONTENT_CHARS + 50)]);
    const file = new File(["ignored"], "doc.pdf", { type: "application/pdf" });

    const { processFile, attachedFile } = useFileAttachment();
    await processFile(file);

    expect(attachedFile.value?.content.length).toBe(MAX_CONTENT_CHARS);
  });

  it("sets a pdf-specific error message when extraction throws", async () => {
    getDocumentMock.mockReturnValue({ promise: Promise.reject(new Error("boom")) });
    const file = new File(["ignored"], "doc.pdf", { type: "application/pdf" });

    const { processFile, attachmentError, attachedFile } = useFileAttachment();
    await processFile(file);

    expect(attachmentError.value).toBe("Could not read PDF");
    expect(attachedFile.value).toBeNull();
  });
});

describe("processFile - read failures", () => {
  it("sets a generic error message when reading a text file fails", async () => {
    vi.stubGlobal("FileReader", FakeFailingFileReader);
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });

    const { processFile, attachmentError, attachedFile } = useFileAttachment();
    await processFile(file);

    expect(attachmentError.value).toBe("Failed to read file");
    expect(attachedFile.value).toBeNull();
  });
});

describe("processFile - loading state", () => {
  it("attachmentLoading is true while reading, false after success", async () => {
    let resolveRead: () => void;
    const deferred = new Promise<void>((resolve) => {
      resolveRead = resolve;
    });

    class DeferredFileReader {
      onload: (() => void) | null = null;
      onerror: (() => void) | null = null;
      result: string | null = null;
      readAsText(file: File) {
        deferred.then(() => {
          file.text().then((text) => {
            this.result = text;
            this.onload?.();
          });
        });
      }
    }
    vi.stubGlobal("FileReader", DeferredFileReader);

    const { processFile, attachmentLoading } = useFileAttachment();
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });

    const pending = processFile(file);
    expect(attachmentLoading.value).toBe(true);

    resolveRead!();
    await pending;

    expect(attachmentLoading.value).toBe(false);
  });

  it("attachmentLoading goes back to false on the error path too", async () => {
    vi.stubGlobal("FileReader", FakeFailingFileReader);
    const { processFile, attachmentLoading } = useFileAttachment();
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });

    await processFile(file);

    expect(attachmentLoading.value).toBe(false);
  });
});

describe("clearAttachment", () => {
  it("resets all three refs regardless of prior state", async () => {
    const { processFile, clearAttachment, attachedFile, attachmentError, attachmentLoading } =
      useFileAttachment();
    const file = new File(["hello"], "notes.txt", { type: "text/plain" });
    await processFile(file);
    expect(attachedFile.value).not.toBeNull();

    clearAttachment();

    expect(attachedFile.value).toBeNull();
    expect(attachmentError.value).toBeNull();
    expect(attachmentLoading.value).toBe(false);
  });
});
