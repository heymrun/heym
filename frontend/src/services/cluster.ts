import api from "@/services/api";

import type { ClusterInstanceUpdate, ClusterSettings } from "@/types/cluster";

export async function getClusterSettings(): Promise<ClusterSettings> {
  const { data } = await api.get<ClusterSettings>("/admin/cluster");
  return data;
}

export async function saveClusterInstances(
  updates: Record<string, ClusterInstanceUpdate>,
): Promise<ClusterSettings> {
  const { data } = await api.put<ClusterSettings>("/admin/cluster/instances", updates);
  return data;
}

export async function setAutomaticWeighting(enabled: boolean): Promise<ClusterSettings> {
  const { data } = await api.put<ClusterSettings>("/admin/cluster", {
    automatic_weighting: enabled,
  });
  return data;
}

export async function removeClusterInstance(instanceId: string): Promise<void> {
  await api.delete(`/admin/cluster/instances/${instanceId}`);
}
