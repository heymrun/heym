import api from "@/services/api";

import type { PluginSummary } from "@/types/workflow";

export interface PluginDoc {
  id: string;
  name: string;
  doc_slug: string;
  markdown: string;
}

export async function listPlugins(): Promise<PluginSummary[]> {
  const { data } = await api.get<PluginSummary[]>("/plugins");
  return data;
}

export async function getPluginDoc(pluginId: string): Promise<PluginDoc> {
  const { data } = await api.get<PluginDoc>(`/plugins/${pluginId}/doc`);
  return data;
}

export async function installPlugin(file: File): Promise<PluginSummary> {
  const form = new FormData();
  form.append("file", file);
  const { data } = await api.post<PluginSummary>("/plugins/install", form, {
    headers: { "Content-Type": "multipart/form-data" },
  });
  return data;
}

export async function setPluginEnabled(
  pluginId: string,
  enabled: boolean,
): Promise<PluginSummary> {
  const { data } = await api.patch<PluginSummary>(
    `/plugins/${pluginId}?enabled=${enabled}`,
  );
  return data;
}

export async function uninstallPlugin(pluginId: string): Promise<void> {
  await api.delete(`/plugins/${pluginId}`);
}

export async function fetchPluginIconSvg(
  pluginId: string,
  nodeKey?: string,
): Promise<string> {
  const { data } = await api.get<string>(`/plugins/${pluginId}/icon`, {
    params: nodeKey ? { node: nodeKey } : undefined,
    responseType: "text",
  });
  return typeof data === "string" ? data : "";
}
