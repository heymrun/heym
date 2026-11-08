import { computed, inject, ref } from "vue";
import type { ComputedRef, Ref } from "vue";

import { chatFilesPortKey, type ChatFilesPort } from "@/ports";
import { readsAsUtf8Text } from "@/lib/textFileSniff";
import type { FileAttachmentPayload } from "@/types/chat";

export interface AttachedFile {
  /** Stable list key; also what `removeAttachment` takes. */
  key: string;
  name: string;
  kind: "text" | "image" | "pdf" | "zip" | "file";
  mimeType: string;
  content: string;
  sizeKb: number;
  /** kind "file": the Drive file the chat opens in the file sandbox. */
  fileId?: string;
  /** True while the file is read or uploaded; it is not sent until it is ready. */
  pending: boolean;
}

/** Files one chat message carries at most, as the server enforces (`MAX_CHAT_ATTACHMENTS`). */
export const MAX_ATTACHMENTS = 10;

/**
 * Documents go to Drive and are opened in the file sandbox, never pasted into the chat. Images
 * go there too when the host stores chat files, so the sandbox reads their text with OCR.
 */
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

type FileKind = AttachedFile["kind"];

/**
 * The kind a file attaches as. A name the lists do not know is still plain text when it reads
 * as UTF-8: it goes where a `.txt` goes (Drive), or inline when the host has no Drive uploads.
 */
async function detectKind(file: File, toDriveAvailable: boolean): Promise<FileKind | null> {
  const ext = file.name.includes(".") ? (file.name.split(".").pop() ?? "").toLowerCase() : "";
  if (ext === "zip" || file.type === "application/zip" || file.type === "application/x-zip-compressed") {
    return "zip";
  }
  if (IMAGE_MIME_TYPES.has(file.type)) return "image";
  if (DRIVE_EXTENSIONS.has(ext) || file.type === "application/pdf") {
    if (toDriveAvailable) return "file";
  } else if (TEXT_EXTENSIONS.has(ext)) {
    return "text";
  }
  if (await readsAsUtf8Text(file)) return toDriveAvailable ? "file" : "text";
  return null;
}

function maxInlineBytes(kind: FileKind): number {
  if (kind === "image") return MAX_IMAGE_BYTES;
  if (kind === "zip") return MAX_ZIP_BYTES;
  if (kind === "text") return MAX_TEXT_BYTES;
  return Number.POSITIVE_INFINITY;
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

/** The files a drop carries; empty when it carries none. */
export function transferFiles(transfer: DataTransfer | null | undefined): File[] {
  return transfer ? Array.from(transfer.files) : [];
}

/**
 * The files a paste carries. Copied spreadsheet cells and rich text also carry a picture of
 * themselves; they paste as text, so files count only when the paste has no rich text.
 */
export function pastedFiles(clipboard: DataTransfer | null | undefined): File[] {
  if (!clipboard) return [];
  const types = Array.from(clipboard.types);
  if (types.includes("text/html") && types.includes("text/plain")) return [];
  return Array.from(clipboard.files);
}

export interface FileAttachmentState {
  attachedFiles: Ref<AttachedFile[]>;
  /** One line per file that could not be attached, such as "x.exe: Unsupported file type". */
  attachmentErrors: Ref<string[]>;
  attachmentLoading: ComputedRef<boolean>;
  /** The ready files as the API takes them, in the order they were attached. */
  attachmentPayloads: ComputedRef<FileAttachmentPayload[]>;
  addFiles: (files: Iterable<File>) => Promise<void>;
  removeAttachment: (key: string) => void;
  dismissAttachmentErrors: () => void;
  clearAttachments: () => void;
}

let nextKey = 0;

/**
 * Several files per message. `chatFiles` defaults to the host's port and is optional, so a
 * host without document uploads still takes text, images and zips.
 */
export function useFileAttachment(
  chatFiles: ChatFilesPort | null = inject(chatFilesPortKey, null),
): FileAttachmentState {
  const attachedFiles = ref<AttachedFile[]>([]);
  const attachmentErrors = ref<string[]>([]);
  const attachmentLoading = computed(() => attachedFiles.value.some((file) => file.pending));
  const attachmentPayloads = computed(() =>
    attachedFiles.value.filter((file) => !file.pending).map(toAttachmentPayload),
  );

  function update(key: string, patch: Partial<AttachedFile>): void {
    attachedFiles.value = attachedFiles.value.map((file) =>
      file.key === key ? { ...file, ...patch } : file,
    );
  }

  function drop(key: string): void {
    attachedFiles.value = attachedFiles.value.filter((file) => file.key !== key);
  }

  function fail(file: File, reason: string): void {
    attachmentErrors.value = [...attachmentErrors.value, `${file.name}: ${reason}`];
  }

  async function addFile(file: File, key: string): Promise<void> {
    const kind = await detectKind(file, chatFiles !== null);
    if (!kind) {
      drop(key);
      fail(file, "Unsupported file type");
      return;
    }
    const toDrive = chatFiles !== null && (kind === "file" || kind === "image");
    // Drive enforces its own upload limit and answers with the reason.
    const maxBytes = toDrive ? Number.POSITIVE_INFINITY : maxInlineBytes(kind);
    if (file.size > maxBytes) {
      drop(key);
      fail(file, `File too large (max ${maxBytes / (1024 * 1024)} MB)`);
      return;
    }
    try {
      if (toDrive) {
        const stored = await chatFiles.upload(file);
        update(key, {
          name: stored.name,
          kind: "file",
          mimeType: stored.mime,
          sizeKb: Math.round(stored.size / 1024),
          fileId: stored.id,
          pending: false,
        });
        return;
      }
      let content: string;
      if (kind === "image" || kind === "zip") {
        content = await readFileAsDataURL(file);
      } else {
        content = (await readFileAsText(file)).slice(0, MAX_CONTENT_CHARS);
      }
      update(key, { kind, content, pending: false });
    } catch (error: unknown) {
      drop(key);
      fail(file, toDrive && error instanceof Error ? error.message : "Failed to read file");
    }
  }

  /** Attach files in the order given; each one is read or uploaded alongside the others. */
  async function addFiles(files: Iterable<File>): Promise<void> {
    const incoming = Array.from(files);
    if (incoming.length === 0) return;
    attachmentErrors.value = [];
    const room = MAX_ATTACHMENTS - attachedFiles.value.length;
    const accepted = incoming.slice(0, Math.max(room, 0));
    for (const file of incoming.slice(accepted.length)) {
      fail(file, `Attach at most ${MAX_ATTACHMENTS} files to one message`);
    }
    const placed = accepted.map((file) => {
      nextKey += 1;
      return {
        file,
        entry: {
          key: `attachment-${nextKey}`,
          name: file.name,
          kind: "file",
          mimeType: file.type,
          content: "",
          sizeKb: Math.round(file.size / 1024),
          pending: true,
        } satisfies AttachedFile,
      };
    });
    attachedFiles.value = [...attachedFiles.value, ...placed.map((item) => item.entry)];
    await Promise.all(placed.map((item) => addFile(item.file, item.entry.key)));
  }

  function removeAttachment(key: string): void {
    drop(key);
  }

  function dismissAttachmentErrors(): void {
    attachmentErrors.value = [];
  }

  function clearAttachments(): void {
    attachedFiles.value = [];
    attachmentErrors.value = [];
  }

  return {
    attachedFiles,
    attachmentErrors,
    attachmentLoading,
    attachmentPayloads,
    addFiles,
    removeAttachment,
    dismissAttachmentErrors,
    clearAttachments,
  };
}
