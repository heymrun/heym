export type KeyRotationState = "running" | "paused" | "completed";

export interface KeyRotationInstance {
  id: string;
  name: string;
  live: boolean;
  primary_fingerprint: string;
  decrypt_fingerprints: string[];
}

export interface KeyRotationProgress {
  id: string;
  state: KeyRotationState;
  target_fingerprint: string;
  retired_fingerprints: string[];
  done: number;
  remaining: number;
  unreadable: number;
  message: string;
  started_at: string;
  completed_at: string | null;
}

export interface UnreadableCredential {
  id: string;
  name: string;
  type: string;
  owner_email: string;
  updated_at: string | null;
}

export interface KeyRotationStatus {
  primary_fingerprint: string;
  decrypt_fingerprints: string[];
  instances: KeyRotationInstance[];
  can_start: boolean;
  reason: string;
  rotation: KeyRotationProgress | null;
  unreadable: UnreadableCredential[];
}
