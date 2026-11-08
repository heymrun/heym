import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  MAX_ATTACHMENTS,
  pastedFiles,
  toAttachmentPayload,
  useFileAttachment,
} from "./useFileAttachment";

// `File`/`Blob` are native globals in this Node version (v24) - no jsdom
// needed, construct real `new File([...], name, {type})` instances directly.
// `FileReader` is NOT native in Node though, and readFileAsText/
// readFileAsDataURL both call `new FileReader()` - but only lazily, inside
// addFiles, not at the source module's own top level. That means (unlike
// useTextToSpeech's Audio gotcha) a plain vi.stubGlobal("FileReader", ...) in
// beforeEach is enough here, no vi.hoisted() hoisting trick required, since
// nothing reads the global before the test itself calls addFiles.

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

function storedFile(name: string, size: number, mime: string, id = "file-1"): Record<string, unknown> {
  return { id, name, size, mime };
}

describe("addFiles - documents go to Drive", () => {
  it("uploads a spreadsheet and keeps only its Drive reference", async () => {
    uploadMock.mockResolvedValue(storedFile("q3.xlsx", 4096, "application/vnd.ms-excel"));
    const file = new File([new Uint8Array(10)], "q3.xlsx", { type: "" });

    const { addFiles, attachedFiles, attachmentErrors, attachmentPayloads } =
      useFileAttachment(chatFiles);
    await addFiles([file]);

    expect(attachmentErrors.value).toEqual([]);
    expect(uploadMock).toHaveBeenCalledWith(file);
    expect(attachedFiles.value).toEqual([
      expect.objectContaining({
        name: "q3.xlsx",
        kind: "file",
        mimeType: "application/vnd.ms-excel",
        content: "",
        sizeKb: 4,
        fileId: "file-1",
        pending: false,
      }),
    ]);
    expect(attachmentPayloads.value).toEqual([
      { name: "q3.xlsx", kind: "file", content: "", file_id: "file-1" },
    ]);
  });

  it("sends PDFs to Drive instead of extracting their text in the browser", async () => {
    uploadMock.mockResolvedValue(storedFile("doc.pdf", 2048, "application/pdf"));
    const file = new File(["%PDF"], "notes.txt", { type: "application/pdf" });

    const { addFiles, attachedFiles } = useFileAttachment(chatFiles);
    await addFiles([file]);

    expect(attachedFiles.value[0].kind).toBe("file");
    expect(attachedFiles.value[0].content).toBe("");
  });

  it("shows the server's reason when Drive refuses the upload", async () => {
    uploadMock.mockRejectedValue(new Error("File size exceeds limit (100 MB)"));
    const file = new File(["a,b"], "big.csv", { type: "text/csv" });

    const { addFiles, attachmentErrors, attachedFiles } = useFileAttachment(chatFiles);
    await addFiles([file]);

    expect(attachmentErrors.value).toEqual(["big.csv: File size exceeds limit (100 MB)"]);
    expect(attachedFiles.value).toEqual([]);
  });

  it("builds a request payload with the file id and no content", () => {
    const payload = toAttachmentPayload({
      key: "k",
      name: "q3.xlsx",
      kind: "file",
      mimeType: "",
      content: "",
      sizeKb: 1,
      fileId: "file-1",
      pending: false,
    });
    expect(payload).toEqual({ name: "q3.xlsx", kind: "file", content: "", file_id: "file-1" });
  });
});

describe("addFiles - several files", () => {
  it("attaches every file in the order given, even when uploads finish out of order", async () => {
    let releaseFirst: (value: unknown) => void = () => {};
    uploadMock
      .mockImplementationOnce(
        () => new Promise((resolve) => (releaseFirst = () => resolve(storedFile("a.pdf", 1024, "application/pdf", "id-a")))),
      )
      .mockResolvedValueOnce(storedFile("b.csv", 1024, "text/csv", "id-b"));
    const { addFiles, attachedFiles, attachmentLoading, attachmentPayloads } =
      useFileAttachment(chatFiles);

    const done = addFiles([
      new File(["%PDF"], "a.pdf", { type: "application/pdf" }),
      new File(["x,y"], "b.csv", { type: "text/csv" }),
    ]);
    await vi.waitFor(() => expect(attachedFiles.value[1]?.pending).toBe(false));
    expect(attachmentLoading.value).toBe(true);
    expect(attachmentPayloads.value.map((item) => item.file_id)).toEqual(["id-b"]);

    releaseFirst(null);
    await done;

    expect(attachmentLoading.value).toBe(false);
    expect(attachedFiles.value.map((file) => file.name)).toEqual(["a.pdf", "b.csv"]);
    expect(attachmentPayloads.value.map((item) => item.file_id)).toEqual(["id-a", "id-b"]);
  });

  it("keeps the files that work when one of them is refused", async () => {
    uploadMock.mockResolvedValue(storedFile("q3.xlsx", 1024, ""));
    const { addFiles, attachedFiles, attachmentErrors } = useFileAttachment(chatFiles);

    await addFiles([
      new File([new Uint8Array([0, 1, 2, 0])], "tool.exe", { type: "application/octet-stream" }),
      new File([new Uint8Array(10)], "q3.xlsx", { type: "" }),
    ]);

    expect(attachedFiles.value.map((file) => file.name)).toEqual(["q3.xlsx"]);
    expect(attachmentErrors.value).toEqual(["tool.exe: Unsupported file type"]);
  });

  it("adds to the files already attached and refuses the ones over the limit", async () => {
    const { addFiles, attachedFiles, attachmentErrors } = useFileAttachment(null);
    const files = (count: number, prefix: string): File[] =>
      Array.from({ length: count }, (_, index) => new File(["x"], `${prefix}${index}.py`));

    await addFiles(files(MAX_ATTACHMENTS - 1, "a"));
    await addFiles(files(3, "b"));

    expect(attachedFiles.value).toHaveLength(MAX_ATTACHMENTS);
    expect(attachedFiles.value.at(-1)?.name).toBe("b0.py");
    expect(attachmentErrors.value).toEqual([
      `b1.py: Attach at most ${MAX_ATTACHMENTS} files to one message`,
      `b2.py: Attach at most ${MAX_ATTACHMENTS} files to one message`,
    ]);
  });

  it("removes one file by its key and clears them all", async () => {
    const { addFiles, attachedFiles, removeAttachment, clearAttachments } = useFileAttachment(null);
    await addFiles([new File(["a"], "a.py"), new File(["b"], "b.py")]);

    removeAttachment(attachedFiles.value[0].key);
    expect(attachedFiles.value.map((file) => file.name)).toEqual(["b.py"]);

    clearAttachments();
    expect(attachedFiles.value).toEqual([]);
  });
});

describe("addFiles - plain text with any name", () => {
  it("sends a UTF-8 file with an unknown extension to Drive like a .txt", async () => {
    uploadMock.mockResolvedValue(storedFile("burak.akgun", 65, "application/octet-stream"));
    const file = new File(["4 rfc ve pr\n\n5 açık issue\n"], "burak.akgun", { type: "" });

    const { addFiles, attachedFiles, attachmentErrors } = useFileAttachment(chatFiles);
    await addFiles([file]);

    expect(attachmentErrors.value).toEqual([]);
    expect(uploadMock).toHaveBeenCalledWith(file);
    expect(attachedFiles.value[0]).toEqual(
      expect.objectContaining({ name: "burak.akgun", kind: "file", fileId: "file-1" }),
    );
  });

  it("reads a UTF-8 file without an extension inline when the host has no Drive uploads", async () => {
    const { addFiles, attachedFiles } = useFileAttachment(null);
    await addFiles([new File(["all: build\n"], "Makefile", { type: "" })]);

    expect(attachedFiles.value[0]).toEqual(
      expect.objectContaining({ name: "Makefile", kind: "text", content: "all: build\n" }),
    );
  });

  it("reads a text document inline when the host has no Drive uploads", async () => {
    const { addFiles, attachedFiles, attachmentErrors } = useFileAttachment(null);
    await addFiles([new File(["a,b\n1,2"], "data.csv", { type: "text/csv" })]);

    expect(attachmentErrors.value).toEqual([]);
    expect(attachedFiles.value[0]).toEqual(
      expect.objectContaining({ kind: "text", content: "a,b\n1,2" }),
    );
  });

  it("refuses a binary document when the host has no Drive uploads", async () => {
    const { addFiles, attachmentErrors } = useFileAttachment(null);
    await addFiles([new File([new Uint8Array([0x25, 0x50, 0x00, 0xff])], "scan.pdf", { type: "application/pdf" })]);

    expect(attachmentErrors.value).toEqual(["scan.pdf: Unsupported file type"]);
  });
});

describe("addFiles - zip", () => {
  it("keeps a zip as a data URL so the server can unpack it", async () => {
    const { addFiles, attachedFiles, attachmentErrors } = useFileAttachment(null);
    const file = new File([new Uint8Array([0x50, 0x4b, 0x03, 0x04])], "skill.zip", {
      type: "application/zip",
    });

    await addFiles([file]);

    expect(attachmentErrors.value).toEqual([]);
    expect(attachedFiles.value[0].kind).toBe("zip");
    expect(attachedFiles.value[0].content.startsWith("data:")).toBe(true);
    expect(uploadMock).not.toHaveBeenCalled();
  });
});

describe("addFiles - unsupported/oversized files", () => {
  it("refuses a binary file, without reading it", async () => {
    const FileReaderSpy = vi.fn();
    vi.stubGlobal("FileReader", FileReaderSpy);

    const { addFiles, attachmentErrors, attachedFiles } = useFileAttachment(null);
    const file = new File([new Uint8Array([0x4d, 0x5a, 0x00, 0x90])], "x.exe", {
      type: "application/octet-stream",
    });

    await addFiles([file]);

    expect(attachmentErrors.value).toEqual(["x.exe: Unsupported file type"]);
    expect(attachedFiles.value).toEqual([]);
    expect(FileReaderSpy).not.toHaveBeenCalled();
  });

  it("rejects an inline text file over the text size limit", async () => {
    const MAX_TEXT_BYTES = 500 * 1024;
    const FileReaderSpy = vi.fn();
    vi.stubGlobal("FileReader", FileReaderSpy);
    const oversized = new File(["a".repeat(MAX_TEXT_BYTES + 1)], "server.log", {
      type: "text/plain",
    });

    const { addFiles, attachmentErrors, attachedFiles } = useFileAttachment(null);
    await addFiles([oversized]);

    expect(attachmentErrors.value[0]).toContain("File too large");
    expect(attachedFiles.value).toEqual([]);
    expect(FileReaderSpy).not.toHaveBeenCalled();
  });

  it("rejects an image file over the image size limit", async () => {
    const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
    const FileReaderSpy = vi.fn();
    vi.stubGlobal("FileReader", FileReaderSpy);
    const oversized = new File([new Uint8Array(MAX_IMAGE_BYTES + 1)], "photo.png", {
      type: "image/png",
    });

    const { addFiles, attachmentErrors, attachedFiles } = useFileAttachment(null);
    await addFiles([oversized]);

    expect(attachmentErrors.value[0]).toContain("File too large");
    expect(attachedFiles.value).toEqual([]);
    expect(FileReaderSpy).not.toHaveBeenCalled();
  });
});

describe("addFiles - inline text files", () => {
  it("reads a code file's content and populates the attachment with correct metadata", async () => {
    const file = new File(["print('hi')"], "script.py", { type: "text/x-python" });

    const { addFiles, attachedFiles } = useFileAttachment(null);
    await addFiles([file]);

    expect(attachedFiles.value[0]).toEqual(
      expect.objectContaining({
        name: "script.py",
        kind: "text",
        mimeType: "text/x-python",
        content: "print('hi')",
        sizeKb: Math.round(file.size / 1024),
        pending: false,
      }),
    );
  });

  it("truncates text content longer than MAX_CONTENT_CHARS", async () => {
    const MAX_CONTENT_CHARS = 100_000;
    const longText = "a".repeat(MAX_CONTENT_CHARS + 50);
    const file = new File([longText], "server.log", { type: "text/plain" });

    const { addFiles, attachedFiles } = useFileAttachment(null);
    await addFiles([file]);

    expect(attachedFiles.value[0].content.length).toBe(MAX_CONTENT_CHARS);
  });

  it("sets a generic error message when reading a text file fails", async () => {
    vi.stubGlobal("FileReader", FakeFailingFileReader);
    const file = new File(["hello"], "server.log", { type: "text/plain" });

    const { addFiles, attachmentErrors, attachedFiles } = useFileAttachment(null);
    await addFiles([file]);

    expect(attachmentErrors.value).toEqual(["server.log: Failed to read file"]);
    expect(attachedFiles.value).toEqual([]);
  });
});

describe("addFiles - image files", () => {
  it("uploads an image to Drive like a document when the host stores chat files", async () => {
    uploadMock.mockResolvedValue(storedFile("screen.png", 6 * 1024 * 1024, "image/png"));
    const FileReaderSpy = vi.fn();
    vi.stubGlobal("FileReader", FileReaderSpy);
    const file = new File([new Uint8Array(6 * 1024 * 1024)], "screen.png", { type: "image/png" });

    const { addFiles, attachedFiles, attachmentErrors, attachmentPayloads } =
      useFileAttachment(chatFiles);
    await addFiles([file]);

    expect(uploadMock).toHaveBeenCalledWith(file);
    expect(attachmentErrors.value).toEqual([]);
    expect(attachedFiles.value[0]).toEqual(
      expect.objectContaining({
        name: "screen.png",
        kind: "file",
        mimeType: "image/png",
        content: "",
        sizeKb: 6144,
        fileId: "file-1",
      }),
    );
    expect(attachmentPayloads.value).toEqual([
      { name: "screen.png", kind: "file", content: "", file_id: "file-1" },
    ]);
    expect(FileReaderSpy).not.toHaveBeenCalled();
  });

  it("shows Drive's refusal of an image upload", async () => {
    uploadMock.mockRejectedValue(new Error("Drive is full"));
    const file = new File([new Uint8Array([1])], "screen.png", { type: "image/png" });

    const { addFiles, attachmentErrors } = useFileAttachment(chatFiles);
    await addFiles([file]);

    expect(attachmentErrors.value).toEqual(["screen.png: Drive is full"]);
  });

  it("reads an image file as a data URL", async () => {
    const file = new File([new Uint8Array([1, 2, 3])], "photo.png", { type: "image/png" });

    const { addFiles, attachedFiles } = useFileAttachment(null);
    await addFiles([file]);

    expect(attachedFiles.value[0].content.startsWith("data:image/png;base64,")).toBe(true);
  });
});

describe("pastedFiles", () => {
  const image = new File([new Uint8Array([1])], "image.png", { type: "image/png" });
  const clipboard = (types: string[], files: File[]): DataTransfer =>
    ({ types, files }) as unknown as DataTransfer;

  it("attaches a pasted screenshot or copied files", () => {
    expect(pastedFiles(clipboard(["Files"], [image]))).toEqual([image]);
    expect(pastedFiles(clipboard(["text/plain", "Files"], [image]))).toEqual([image]);
  });

  it("pastes copied spreadsheet cells and rich text as text, not as their picture", () => {
    expect(pastedFiles(clipboard(["text/plain", "text/html", "Files"], [image]))).toEqual([]);
  });

  it("has nothing to attach without a clipboard or files", () => {
    expect(pastedFiles(null)).toEqual([]);
    expect(pastedFiles(clipboard(["text/plain"], []))).toEqual([]);
  });
});
