import { readsAsUtf8Text } from "@/lib/textFileSniff";

export type InputFieldFileKind = "text" | "image" | "pdf";

export interface InputFieldFileResult {
  content: string;
  name: string;
  kind: InputFieldFileKind;
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

/** A name the list does not know is still text when the file reads as UTF-8 (`notes`, `a.list`). */
async function detectKind(file: File): Promise<InputFieldFileKind | null> {
  if (file.type === "application/pdf") return "pdf";
  if (IMAGE_MIME_TYPES.has(file.type)) return "image";
  const ext = file.name.includes(".") ? (file.name.split(".").pop() ?? "").toLowerCase() : "";
  if (TEXT_EXTENSIONS.has(ext)) return "text";
  if (await readsAsUtf8Text(file)) return "text";
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

/** Read a dropped or selected file into a workflow input field value string. */
export async function readFileForInputField(file: File): Promise<InputFieldFileResult> {
  const kind = await detectKind(file);
  if (!kind) {
    throw new Error("Unsupported file type");
  }

  const maxBytes =
    kind === "image" ? MAX_IMAGE_BYTES : kind === "pdf" ? MAX_PDF_BYTES : MAX_TEXT_BYTES;
  if (file.size > maxBytes) {
    const maxMb = maxBytes / (1024 * 1024);
    throw new Error(`File too large (max ${maxMb} MB)`);
  }

  let content: string;
  try {
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
  } catch {
    throw new Error(kind === "pdf" ? "Could not read PDF" : "Failed to read file");
  }

  return { content, name: file.name, kind };
}
