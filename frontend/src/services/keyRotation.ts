import api from "@/services/api";

import type { KeyRotationStatus } from "@/types/keyRotation";

export async function getKeyRotation(): Promise<KeyRotationStatus> {
  const { data } = await api.get<KeyRotationStatus>("/admin/key-rotation");
  return data;
}

/** Start re-encrypting stored values under ENCRYPTION_KEY. 409 says why it can't start. */
export async function startKeyRotation(): Promise<KeyRotationStatus> {
  const { data } = await api.post<KeyRotationStatus>("/admin/key-rotation");
  return data;
}
