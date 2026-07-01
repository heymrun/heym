import { ref, type Ref } from "vue";

import type { DocCategory } from "@/docs/manifest";
import type { PluginSummary } from "@/types/workflow";

import { listPlugins } from "@/services/plugins";

export interface PluginDocCategoriesState {
  pluginDocCategories: Ref<Record<string, DocCategory>>;
  loadPluginDocCategories: () => Promise<void>;
}

const pluginDocCategories = ref<Record<string, DocCategory>>({});
let pendingLoad: Promise<void> | null = null;

export function buildPluginDocCategories(
  plugins: PluginSummary[],
): Record<string, DocCategory> {
  if (plugins.length === 0) return {};

  return {
    plugins: {
      id: "plugins",
      label: "Plugins",
      items: plugins.map((plugin) => ({
        slug: plugin.id,
        title: plugin.name,
      })),
    },
  };
}

async function fetchPluginDocCategories(): Promise<void> {
  try {
    pluginDocCategories.value = buildPluginDocCategories(await listPlugins());
  } catch {
    pluginDocCategories.value = {};
  }
}

function loadPluginDocCategories(): Promise<void> {
  if (!pendingLoad) {
    pendingLoad = fetchPluginDocCategories().finally(() => {
      pendingLoad = null;
    });
  }
  return pendingLoad;
}

export function usePluginDocCategories(): PluginDocCategoriesState {
  return {
    pluginDocCategories,
    loadPluginDocCategories,
  };
}
