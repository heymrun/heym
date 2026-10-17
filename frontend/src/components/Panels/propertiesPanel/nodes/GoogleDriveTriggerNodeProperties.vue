<script setup lang="ts">
import { computed } from "vue";
import { AlertTriangle } from "lucide-vue-next";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { driveEventOptions, selectedEvents, toggleEvent } from "@/lib/googleTriggerConfig";
import type { GoogleTriggerEvent } from "@/types/workflow";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const { selectedNode, isWorkflowOwner, googleDriveCredentialOptions, updateNodeData } =
  usePropertiesPanelContext();

const scopeOptions = [
  { value: "folder", label: "Files in a folder" },
  { value: "file", label: "One file" },
];

const scope = computed<"folder" | "file">(() =>
  selectedNode.value?.data.gdtScope === "file" ? "file" : "folder",
);
const eventOptions = computed(() => driveEventOptions(scope.value));
const events = computed<GoogleTriggerEvent[]>(() => selectedEvents(selectedNode.value?.data.gdtEvents));

function setEvent(event: GoogleTriggerEvent, enabled: boolean): void {
  updateNodeData("gdtEvents", toggleEvent(events.value, event, enabled));
}
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div
        class="space-y-2"
        data-testid="gdt-credential-field"
      >
        <Label>Google Drive Credential</Label>
        <Select
          :model-value="selectedNode.data.credentialId || ''"
          :options="googleDriveCredentialOptions"
          :disabled="!isWorkflowOwner"
          @update:model-value="updateNodeData('credentialId', $event)"
        />
        <p
          v-if="!selectedNode.data.credentialId"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          No Google Drive credential set: polling is off
        </p>
      </div>

      <div
        class="space-y-2"
        data-testid="gdt-scope-field"
      >
        <Label>Watch</Label>
        <Select
          :model-value="scope"
          :options="scopeOptions"
          @update:model-value="updateNodeData('gdtScope', $event || 'folder')"
        />
      </div>

      <div
        v-if="scope === 'folder'"
        class="space-y-2"
        data-testid="gdt-folder-field"
      >
        <Label for="gdt-folder-id">Folder ID or URL</Label>
        <Input
          id="gdt-folder-id"
          :model-value="selectedNode.data.gdtFolderId || ''"
          placeholder="Empty watches My Drive"
          @update:model-value="updateNodeData('gdtFolderId', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Only files directly inside this folder are watched.
        </p>
      </div>

      <div
        v-else
        class="space-y-2"
        data-testid="gdt-file-field"
      >
        <Label for="gdt-file-id">File ID or URL</Label>
        <Input
          id="gdt-file-id"
          :model-value="selectedNode.data.gdtFileId || ''"
          @update:model-value="updateNodeData('gdtFileId', $event)"
        />
      </div>

      <div
        class="space-y-2"
        data-testid="gdt-events-field"
      >
        <Label>Start a run when</Label>
        <div
          v-for="option in eventOptions"
          :key="option.value"
          class="flex items-center gap-2"
        >
          <input
            :id="`gdt-event-${option.value}`"
            type="checkbox"
            class="rounded border-border"
            :checked="events.includes(option.value)"
            @change="setEvent(option.value, ($event.target as HTMLInputElement).checked)"
          >
          <label
            :for="`gdt-event-${option.value}`"
            class="text-xs cursor-pointer select-none"
          >{{ option.label }}</label>
        </div>
        <p class="text-xs text-muted-foreground">
          Deleted also covers files moved to the trash or out of the folder.
        </p>
      </div>

      <div
        v-if="scope === 'folder'"
        class="flex items-center gap-2"
        data-testid="gdt-include-folders-field"
      >
        <input
          id="gdt-include-folders"
          type="checkbox"
          class="rounded border-border"
          :checked="selectedNode.data.gdtIncludeFolders === true"
          @change="updateNodeData('gdtIncludeFolders', ($event.target as HTMLInputElement).checked)"
        >
        <label
          for="gdt-include-folders"
          class="text-xs cursor-pointer select-none"
        >Subfolders also start runs</label>
      </div>

      <div
        class="space-y-2"
        data-testid="gdt-poll-field"
      >
        <Label for="gdt-poll-interval">Poll Interval (Minutes)</Label>
        <Input
          id="gdt-poll-interval"
          :model-value="String(selectedNode.data.pollIntervalMinutes ?? 1)"
          type="number"
          min="1"
          step="1"
          @update:model-value="updateNodeData('pollIntervalMinutes', Number.parseInt($event, 10) || 1)"
        />
        <p class="text-xs text-muted-foreground">
          The first poll records the folder as it is. After that, each change starts one run.
        </p>
      </div>

      <div
        class="space-y-2 pt-2 border-t"
        data-testid="gdt-output-fields"
      >
        <Label class="text-xs text-muted-foreground">Available output fields</Label>
        <div class="text-xs text-muted-foreground space-y-1 font-mono">
          <div>${{ selectedNode.data.label }}.event: created, updated, or deleted</div>
          <div>${{ selectedNode.data.label }}.file.id: Drive file ID</div>
          <div>${{ selectedNode.data.label }}.file.name: file name</div>
          <div>${{ selectedNode.data.label }}.file.mime_type: file type</div>
          <div>${{ selectedNode.data.label }}.file.web_view_link: link to open the file</div>
          <div>${{ selectedNode.data.label }}.changed_fields: what changed on update</div>
          <div>${{ selectedNode.data.label }}.triggered_at: when the change was seen</div>
        </div>
      </div>
    </div>
  </template>
</template>
