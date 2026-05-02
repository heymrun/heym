import { ref } from "vue";

export interface AttachedFile {
  name: string;
  kind: "text" | "image" | "pdf";
  mimeType: string;
  content: string;
  sizeKb: number;
}

const TEXT_EXTENSIONS = new Set([
  "txt",
  "csv",
  "json",
  "md",
  "py",
  "ts",
  "js",
  "html",
  "xml",
  "yaml",
  "yml",
  "log",
]);
const IMAGE_MIME_TYPES = new Set(["image/jpeg", "image/png", "image/gif", "image/webp"]);
const MAX_TEXT_BYTES = 500 * 1024;
const MAX_IMAGE_BYTES = 5 * 1024 * 1024;
const MAX_PDF_BYTES = 5 * 1024 * 1024;
const MAX_CONTENT_CHARS = 100_000;

function detectKind(file: File): "text" | "image" | "pdf" | null {
  if (file.type === "application/pdf") return "pdf";
  if (IMAGE_MIME_TYPES.has(file.type)) return "image";
  const ext = file.name.split(".").pop()?.toLowerCase() ?? "";
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

async function extractPdfText(file: File): Promise<string> {
  const { getDocument, GlobalWorkerOptions } = await import("pdfjs-dist");
  GlobalWorkerOptions.workerSrc = new URL(
    "pdfjs-dist/build/pdf.worker.min.mjs",
    import.meta.url,
  ).href;
  const buffer = await file.arrayBuffer();
  const pdf = await getDocument({ data: buffer }).promise;
  const pages: string[] = [];
  for (let i = 1; i <= pdf.numPages; i++) {
    const page = await pdf.getPage(i);
    const textContent = await page.getTextContent();
    const pageText = textContent.items
      .map((item: Record<string, unknown>) =>
        typeof item["str"] === "string" ? item["str"] : "",
      )
      .join(" ");
    pages.push(pageText);
  }
  const full = pages.join("\n");
  return full.length > MAX_CONTENT_CHARS ? full.slice(0, MAX_CONTENT_CHARS) : full;
}

export function useFileAttachment() {
  const attachedFile = ref<AttachedFile | null>(null);
  const attachmentError = ref<string | null>(null);
  const attachmentLoading = ref(false);

  async function processFile(file: File): Promise<void> {
    attachmentError.value = null;
    const kind = detectKind(file);
    if (!kind) {
      attachmentError.value = "Unsupported file type";
      return;
    }
    const maxBytes =
      kind === "image" ? MAX_IMAGE_BYTES : kind === "pdf" ? MAX_PDF_BYTES : MAX_TEXT_BYTES;
    if (file.size > maxBytes) {
      const maxMb = maxBytes / (1024 * 1024);
      attachmentError.value = `File too large (max ${maxMb} MB)`;
      return;
    }

    attachmentLoading.value = true;
    try {
      let content: string;
      if (kind === "image") {
        content = await readFileAsDataURL(file);
      } else if (kind === "pdf") {
        content = await extractPdfText(file);
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
    } catch {
      attachmentError.value = kind === "pdf" ? "Could not read PDF" : "Failed to read file";
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
