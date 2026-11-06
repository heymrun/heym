export type K8sCredentialStatus =
  | "available"
  | "unavailable"
  | "invalid"
  | "owner_missing"
  | "name_conflict";

export interface K8sCredential {
  namespace: string;
  secret_name: string;
  credential_id: string;
  name: string;
  type: string;
  owner_email: string;
  status: K8sCredentialStatus;
  detail: string | null;
  warnings: string[];
}

export interface K8sCredentialsState {
  enabled: boolean;
  synced: boolean;
  synced_at: string | null;
  last_error: string | null;
  credentials: K8sCredential[];
}
