export interface GeneratedFile {
  id: string;
  filename: string;
  mime_type: string;
  size_bytes: number;
  workflow_id: string | null;
  source_node_label: string | null;
  download_url: string;
  created_at: string;
}

export interface FileAccessToken {
  id: string;
  token: string;
  download_url: string;
  basic_auth_enabled: boolean;
  expires_at: string | null;
  download_count: number;
  max_downloads: number | null;
  created_at: string;
}

export interface CreateShareRequest {
  expires_hours?: number | null;
  basic_auth_password?: string | null;
  max_downloads?: number | null;
}

export interface FileListResponse {
  files: GeneratedFile[];
  total: number;
}

export interface FileListParams {
  workflow_id?: string;
  mime_type?: string;
  limit?: number;
  offset?: number;
}
