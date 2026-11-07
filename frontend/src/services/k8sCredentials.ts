import api from "@/services/api";

import type { K8sCredentialsState } from "@/types/k8sCredentials";

export async function getK8sCredentials(): Promise<K8sCredentialsState> {
  const { data } = await api.get<K8sCredentialsState>("/admin/k8s-credentials");
  return data;
}

/**
 * Whether this instance reads credentials from Kubernetes Secrets (`HEYM_K8S_CREDENTIALS`).
 * Settings shows the Kubernetes tab only then; an error counts as off.
 */
export async function k8sCredentialsEnabled(): Promise<boolean> {
  try {
    return (await getK8sCredentials()).enabled;
  } catch {
    return false;
  }
}

/** Remove the row of a Secret that no longer exists. */
export async function removeK8sCredential(credentialId: string): Promise<void> {
  await api.delete(`/admin/k8s-credentials/${credentialId}`);
}
