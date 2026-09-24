<script setup lang="ts">
import { computed } from "vue";
import { LayoutGrid, Pencil, Plus, RefreshCw, Settings, Sparkles } from "lucide-vue-next";

import DashboardAutoRefreshControl from "@/components/Dashboards/DashboardAutoRefreshControl.vue";
import Button from "@/components/ui/Button.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import { useDashboardStore } from "@/stores/dashboard";

defineProps<{
  editMode: boolean;
  hasWidgets: boolean;
}>();

const emit = defineEmits<{
  (e: "select", dashboardId: string): void;
  (e: "create"): void;
  (e: "settings"): void;
  (e: "refresh"): void;
  (e: "tidy"): void;
  (e: "toggle-edit"): void;
  (e: "ai"): void;
  (e: "add"): void;
}>();

const dashboardStore = useDashboardStore();

const selectGroups = computed(() => {
  const own = dashboardStore.dashboards.filter((dashboard) => dashboard.permission === "owner");
  const shared = dashboardStore.dashboards.filter((dashboard) => dashboard.permission !== "owner");
  const groups = [
    {
      label: "My dashboards",
      options: own.map((dashboard) => ({ value: dashboard.id, label: dashboard.name })),
    },
  ];
  if (shared.length) {
    groups.push({
      label: "Shared with me",
      options: shared.map((dashboard) => ({
        value: dashboard.id,
        label: `${dashboard.name} · ${dashboard.owner_name || dashboard.shared_by}`,
      })),
    });
  }
  return groups;
});

const sharedBadge = computed<string | null>(() => {
  const dashboard = dashboardStore.activeDashboard;
  if (!dashboard || dashboard.permission === "owner") return null;
  const owner = dashboard.owner_name || dashboard.shared_by;
  return `Shared by ${owner} · ${dashboard.permission === "write" ? "Can edit" : "Can view"}`;
});

function onSelect(dashboardId: string | undefined): void {
  if (dashboardId) emit("select", dashboardId);
}
</script>

<template>
  <div
    data-testid="dashboard-header"
    class="flex flex-col gap-3 border-b px-4 py-3 lg:flex-row lg:items-center lg:justify-between"
  >
    <!-- The selector names the open dashboard, so the tab title is kept for screen readers only. -->
    <h1 class="sr-only">
      Dashboard
    </h1>
    <div class="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-2">
      <!-- SearchableSelect's root is w-full, so its wrapper controls the width. Keyed on the
           name: the combobox caches its display value, so a rename only shows once rebuilt. -->
      <div class="min-w-0 flex-1 sm:w-64 sm:flex-none">
        <SearchableSelect
          :key="dashboardStore.activeDashboard?.name ?? ''"
          :model-value="dashboardStore.activeDashboard?.id ?? ''"
          :groups="selectGroups"
          placeholder="Select dashboard"
          search-placeholder="Search dashboards…"
          aria-label="Select dashboard"
          data-testid="dashboard-select"
          @update:model-value="onSelect"
        />
      </div>
      <Button
        variant="ghost"
        size="icon"
        class="shrink-0"
        title="New dashboard"
        aria-label="New dashboard"
        data-testid="dashboard-new"
        @click="emit('create')"
      >
        <Plus class="h-4 w-4" />
      </Button>
      <Button
        v-if="dashboardStore.isOwner"
        variant="ghost"
        size="icon"
        class="shrink-0"
        title="Dashboard settings and sharing"
        aria-label="Dashboard settings"
        data-testid="dashboard-settings"
        @click="emit('settings')"
      >
        <Settings class="h-4 w-4" />
      </Button>
      <!-- Full-width row on phones so the badge never squeezes the selector. -->
      <div
        v-if="sharedBadge"
        class="min-w-0 basis-full sm:basis-auto"
      >
        <span
          class="inline-block max-w-full truncate rounded bg-muted px-2 py-0.5 align-middle text-xs text-muted-foreground"
          :title="sharedBadge"
          data-testid="dashboard-shared-badge"
        >
          {{ sharedBadge }}
        </span>
      </div>
    </div>
    <div class="flex flex-wrap items-center gap-1 sm:gap-2">
      <DashboardAutoRefreshControl
        class="shrink-0"
        @refresh="emit('refresh')"
      />
      <Button
        variant="ghost"
        size="sm"
        class="h-11 w-11 shrink-0 justify-center px-0 sm:h-auto sm:w-auto sm:px-3"
        title="Refresh dashboard"
        aria-label="Refresh dashboard"
        @click="emit('refresh')"
      >
        <RefreshCw class="h-4 w-4 sm:mr-1" />
        <span class="hidden sm:inline">Refresh</span>
      </Button>
      <template v-if="dashboardStore.canWrite">
        <Button
          v-if="hasWidgets"
          variant="ghost"
          size="sm"
          class="h-11 w-11 shrink-0 justify-center px-0 sm:h-auto sm:w-auto sm:px-3"
          title="Rearrange widgets into a random tidy grid"
          aria-label="Tidy up dashboard"
          @click="emit('tidy')"
        >
          <LayoutGrid class="h-4 w-4 sm:mr-1" />
          <span class="hidden sm:inline">Tidy up</span>
        </Button>
        <Button
          :variant="editMode ? 'default' : 'ghost'"
          size="sm"
          class="h-11 w-11 shrink-0 justify-center px-0 sm:h-auto sm:w-auto sm:px-3"
          :title="editMode ? 'Finish editing dashboard' : 'Edit dashboard'"
          :aria-label="editMode ? 'Finish editing dashboard' : 'Edit dashboard'"
          @click="emit('toggle-edit')"
        >
          <Pencil class="h-4 w-4 sm:mr-1" />
          <span class="hidden sm:inline">{{ editMode ? "Done" : "Edit" }}</span>
        </Button>
        <Button
          variant="ghost"
          size="sm"
          class="h-11 w-11 shrink-0 justify-center px-0 sm:h-auto sm:w-auto sm:px-3"
          title="Generate widget with AI"
          aria-label="Generate widget with AI"
          @click="emit('ai')"
        >
          <Sparkles class="h-4 w-4 sm:mr-1" />
          <span class="hidden sm:inline">AI</span>
        </Button>
        <Button
          size="sm"
          class="h-11 min-w-[4.5rem] flex-1 justify-center px-2 sm:h-auto sm:min-w-0 sm:flex-none sm:px-3"
          title="Add widget"
          aria-label="Add widget"
          @click="emit('add')"
        >
          <Plus class="mr-1 h-4 w-4" />
          <span class="sm:hidden">Add</span>
          <span class="hidden sm:inline">Add widget</span>
        </Button>
      </template>
    </div>
  </div>
</template>
