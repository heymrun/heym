import type { CredentialType } from "@/types/credential";

export type CredentialSetupStatus = "pending" | "completed" | "declined" | "expired";

// A credential form an MCP chat turn opened; the user fills it in on Heym's own page.
export interface CredentialSetupRequest {
  id: string;
  action: "create" | "update";
  credential_type: CredentialType;
  suggested_name: string | null;
  credential_id: string | null;
  reason: string | null;
  status: CredentialSetupStatus;
  expires_at: string;
  completed_at: string | null;
}
