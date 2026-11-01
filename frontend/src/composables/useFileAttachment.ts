import { inject, ref } from "vue";

import { chatFilesPortKey, type ChatFilesPort } from "@/ports";
import type { FileAttachmentPayload } from "@/types/chat";

export interface AttachedFile {
  name: string;
  kind: "text" | "image" | "pdf" | "zip" | "file";
  mimeType: string;
  content: string;
  sizeKb: number;
  /** kind "file": the Drive file the chat opens in the file sandbox. */
  fileId?: string;
}

/** Documents go to Drive and are opened in the file sandbox, never pasted into the chat. */
const DRIVE_EXTENSIONS = new Set([
  "pdf",
  "xlsx",
  "xlsm",
  "xls",
  "csv",
  "tsv",
  "docx",
  "json",
  "jsonl",
  "txt",
  "md",
]);
const TEXT_EXTENSIONS = new Set(["py", "ts", "js", "html", "xml", "yaml", "yml", "log"]);
const IMAGE_MIME_TYPES = new Set(["image/jpeg", "image/png", "image/gif", "image/webp"]);
const MAX_TEXT_BYTES = 500 * 1024;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_ZIP_BYTES = 8 * 1024 * 1024;
const MAX_CONTENT_CHARS = 100_000;

export const ATTACHMENT_ACCEPT = [
  ...[...DRIVE_EXTENSIONS, ...TEXT_EXTENSIONS].map((ext) => `.${ext}`),
  ".jpg",
  ".jpeg",
  ".png",
  ".gif",
  ".webp",
  ".zip",
].join(",");

function detectKind(file: File): AttachedFile["kind"] | null {
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
  if (ext === "zip" || file.type === "application/zip" || file.type === "application/x-zip-compressed") {
    return "zip";
  }
  if (IMAGE_MIME_TYPES.has(file.type)) return "image";
  if (DRIVE_EXTENSIONS.has(ext) || file.type === "application/pdf") return "file";
  if (TEXT_EXTENSIONS.has(ext)) return "text";
  return null;
}

function readFileAsText(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsText(file);
  });
}

function readFileAsDataURL(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(new Error("Failed to read file"));
    reader.readAsDataURL(file);
  });
}

/** The request body for an attachment: a Drive reference, or inline content. */
export function toAttachmentPayload(file: AttachedFile): FileAttachmentPayload {
  if (file.kind === "file") {
    return { name: file.name, kind: "file", content: "", file_id: file.fileId };
  }
  return { name: file.name, kind: file.kind, content: file.content };
}

/**
 * `chatFiles` defaults to the host's port and is optional, so a host without document uploads
 * still takes text, images and zips.
 */
export function useFileAttachment(
  chatFiles: ChatFilesPort | null = inject(chatFilesPortKey, null),
) {
  const attachedFile = ref<AttachedFile | null>(null);
  const attachmentError = ref<string | null>(null);
  const attachmentLoading = ref(false);

  async function processFile(file: File): Promise<void> {
    attachmentError.value = null;
    const kind = detectKind(file);
    if (!kind || (kind === "file" && chatFiles === null)) {
      attachmentError.value = "Unsupported file type";
      return;
    }
    // Drive enforces its own upload limit and answers with the reason.
    const maxBytes =
      kind === "image"
        ? MAX_IMAGE_BYTES
        : kind === "zip"
          ? MAX_ZIP_BYTES
          : kind === "text"
            ? MAX_TEXT_BYTES
            : Number.POSITIVE_INFINITY;
    if (file.size > maxBytes) {
      const maxMb = maxBytes / (1024 * 1024);
      attachmentError.value = `File too large (max ${maxMb} MB)`;
      return;
    }

    attachmentLoading.value = true;
    try {
      if (kind === "file" && chatFiles !== null) {
        const stored = await chatFiles.upload(file);
        attachedFile.value = {
          name: stored.name,
          kind,
          mimeType: stored.mime,
          content: "",
          sizeKb: Math.round(stored.size / 1024),
          fileId: stored.id,
        };
        return;
      }
      let content: string;
      if (kind === "image" || kind === "zip") {
        content = await readFileAsDataURL(file);
      } else {
        content = await readFileAsText(file);
        if (content.length > MAX_CONTENT_CHARS) {
          content = content.slice(0, MAX_CONTENT_CHARS);
        }
      }
      attachedFile.value = {
        name: file.name,
        kind,
        mimeType: file.type,
        content,
        sizeKb: Math.round(file.size / 1024),
      };
    } catch (error: unknown) {
      attachmentError.value =
        kind === "file" && error instanceof Error ? error.message : "Failed to read file";
    } finally {
      attachmentLoading.value = false;
    }
  }

  function clearAttachment(): void {
    attachedFile.value = null;
    attachmentError.value = null;
    attachmentLoading.value = false;
  }

  return { attachedFile, attachmentError, attachmentLoading, processFile, clearAttachment };
}
