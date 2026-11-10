/** A vector store upload Heym reads in the background: audio, or a PDF with scanned pages. */
export interface RagIngestJob {
  id: string;
  filename: string;
  file_size: number;
  kind: "audio" | "pdf";
  status: "queued" | "processing" | "failed";
  error: string | null;
  created_at: string;
  updated_at: string;
}

export interface RagIngestJobList {
  jobs: RagIngestJob[];
  total: number;
}
