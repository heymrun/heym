import { readsAsUtf8Text } from "@/lib/textFileSniff";

/** How a file enters a vector store; mirrors backend/app/services/rag_ingest.py. */
export type RagFileKind = "document" | "image" | "audio" | "text";

export const RAG_DOCUMENT_EXTENSIONS: readonly string[] = [".pdf", ".md", ".markdown", ".txt", ".csv", ".json"];
export const RAG_IMAGE_EXTENSIONS: readonly string[] = [".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp"];
export const RAG_AUDIO_EXTENSIONS: readonly string[] = [".mp3", ".wav", ".ogg", ".flac"];

/** What a vector store takes, for upload dialogs and notices. */
export const RAG_FORMATS_LINE =
  "PDF, Markdown, text, CSV, JSON, images (PNG, JPEG, TIFF, WebP, BMP), audio (mp3, wav, ogg, flac) and any other plain-text file";

function extension(name: string): string {
  const dot = name.lastIndexOf(".");
  return dot >= 0 ? name.slice(dot).toLowerCase() : "";
}

/** How Heym reads a file into a vector store, or null when it cannot: judged as Heym judges it. */
export async function ragFileKind(file: File): Promise<RagFileKind | null> {
  const ext = extension(file.name);
  if (RAG_DOCUMENT_EXTENSIONS.includes(ext)) return "document";
  if (RAG_IMAGE_EXTENSIONS.includes(ext)) return "image";
  if (RAG_AUDIO_EXTENSIONS.includes(ext)) return "audio";
  return (await readsAsUtf8Text(file)) ? "text" : null;
}
