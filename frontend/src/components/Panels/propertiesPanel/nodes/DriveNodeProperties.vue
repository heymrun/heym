<script setup lang="ts">
import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  driveFileOptions,
  driveFileIdExpressionInputRef,
  drivePasswordExpressionInputRef,
  driveFilenameExpressionInputRef,
  driveBase64ContentExpressionInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  driveExpressionFieldCount,
  isDriveFileIdAgentProvided,
  handleDriveExpressionFieldNavigate,
  onDriveRegisterExpressionFieldIndex,
  driveOperationOptions,
  driveConvertFormatOptionsFiltered,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Operation</Label>
      <Select
        :model-value="selectedNode.data.driveOperation || ''"
        :options="driveOperationOptions"
        @update:model-value="updateNodeData('driveOperation', $event || undefined)"
      />
      <p class="text-xs text-muted-foreground">
        File operation to perform
      </p>
    </div>

    <div
      v-if="selectedNode.data.driveOperation === 'downloadUrl'"
      class="space-y-2"
    >
      <Label>Source URL</Label>
      <ExpressionInput
        :model-value="selectedNode.data.driveSourceUrl || ''"
        placeholder="https://example.com/file.pdf"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Source URL"
        @update:model-value="updateNodeData('driveSourceUrl', $event)"
      />
      <p class="text-xs text-muted-foreground">
        URL of the file to download and store in Drive
      </p>
    </div>

    <div
      v-if="selectedNode.data.driveOperation === 'save'"
      class="space-y-4"
    >
      <div class="space-y-2">
        <Label>Filename</Label>
        <ExpressionInput
          ref="driveFilenameExpressionInputRef"
          :model-value="selectedNode.data.driveFilename || ''"
          placeholder="1.mp3"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          expandable
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Drive save · Filename"
          field-key="driveFilename"
          :navigation-enabled="true"
          :navigation-index="0"
          :navigation-total="driveExpressionFieldCount"
          @navigate="handleDriveExpressionFieldNavigate"
          @register-field-index="onDriveRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('driveFilename', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Full filename including extension (for example, 1.mp3)
        </p>
      </div>
      <div class="space-y-2">
        <Label>Base64 Content</Label>
        <ExpressionInput
          ref="driveBase64ContentExpressionInputRef"
          :model-value="selectedNode.data.driveBase64Content || ''"
          placeholder="$userInput.body.base64"
          :rows="3"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          expandable
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Drive save · Base64 Content"
          field-key="driveBase64Content"
          :navigation-enabled="true"
          :navigation-index="1"
          :navigation-total="driveExpressionFieldCount"
          @navigate="handleDriveExpressionFieldNavigate"
          @register-field-index="onDriveRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('driveBase64Content', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Raw base64 string or data URL to decode and store in Drive
        </p>
      </div>
    </div>

    <div
      v-if="selectedNode.data.driveOperation && !['downloadUrl', 'getAll', 'save'].includes(selectedNode.data.driveOperation)"
      class="space-y-2"
    >
      <div class="flex items-center justify-between gap-2">
        <Label>File ID</Label>
        <AgentFieldToggle
          :node-id="selectedNode.id"
          field-key="driveFileId"
        />
      </div>
      <template v-if="selectedNode.data.driveOperation === 'get' || selectedNode.data.driveOperation === 'convertFile'">
        <Select
          :model-value="selectedNode.data.driveFileId || ''"
          :options="driveFileOptions"
          :disabled="isDriveFileIdAgentProvided"
          @update:model-value="updateNodeData('driveFileId', $event || undefined)"
        />
        <div
          v-if="isDriveFileIdAgentProvided"
          class="rounded-md border border-violet-800/30 bg-violet-950/20 px-3 py-2 text-xs italic text-violet-400"
        >
          Agent will provide this at runtime.
        </div>
        <ExpressionInput
          v-else
          ref="driveFileIdExpressionInputRef"
          :model-value="selectedNode.data.driveFileId || ''"
          placeholder="$skill._generated_files[0].id"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          expandable
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="File ID"
          @update:model-value="updateNodeData('driveFileId', $event)"
        />
      </template>
      <template v-else>
        <div
          v-if="isDriveFileIdAgentProvided"
          class="rounded-md border border-violet-800/30 bg-violet-950/20 px-3 py-2 text-xs italic text-violet-400"
        >
          Agent will provide this at runtime.
        </div>
        <ExpressionInput
          v-else
          ref="driveFileIdExpressionInputRef"
          :model-value="selectedNode.data.driveFileId || ''"
          placeholder="$skill._generated_files[0].id"
          :rows="1"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          expandable
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          :dialog-key-label="
            selectedNode.data.driveOperation === 'setPassword'
              ? 'Drive set password · File ID'
              : 'File ID'
          "
          :navigation-enabled="selectedNode.data.driveOperation === 'setPassword'"
          :navigation-index="0"
          :navigation-total="driveExpressionFieldCount"
          @navigate="handleDriveExpressionFieldNavigate"
          @register-field-index="onDriveRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('driveFileId', $event)"
        />
      </template>
      <p class="text-xs text-muted-foreground">
        ID of the file to manage
      </p>
    </div>

    <div
      v-if="selectedNode.data.driveOperation === 'getAll'"
      class="space-y-2"
    >
      <Label>Limit</Label>
      <Input
        type="number"
        :model-value="selectedNode.data.driveLimit ?? ''"
        min="0"
        placeholder="No limit"
        @update:model-value="updateNodeData('driveLimit', $event !== '' ? Number($event) : undefined)"
      />
      <p class="text-xs text-muted-foreground">
        Maximum number of files to return
      </p>
    </div>

    <div
      v-if="selectedNode.data.driveOperation === 'get'"
      class="space-y-2"
    >
      <Label>Options</Label>
      <div class="flex items-center gap-2">
        <input
          id="drive-include-binary"
          type="checkbox"
          class="h-4 w-4 rounded border-input bg-background"
          :checked="!!selectedNode.data.driveIncludeBinary"
          @change="updateNodeData('driveIncludeBinary', ($event.target as HTMLInputElement).checked)"
        >
        <Label
          for="drive-include-binary"
          class="font-normal text-sm"
        >
          Include binary content
        </Label>
      </div>
      <p class="text-xs text-muted-foreground">
        When enabled, the file content is returned as base64 in <code>file_base64</code>
      </p>
    </div>

    <div
      v-if="selectedNode.data.driveOperation === 'setPassword'"
      class="space-y-2"
    >
      <Label>Password</Label>
      <ExpressionInput
        ref="drivePasswordExpressionInputRef"
        :model-value="selectedNode.data.drivePassword || ''"
        placeholder="Enter password or expression"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="drivePassword"
        expandable
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Drive set password · Password"
        navigation-enabled
        :navigation-index="1"
        :navigation-total="driveExpressionFieldCount"
        @navigate="handleDriveExpressionFieldNavigate"
        @register-field-index="onDriveRegisterExpressionFieldIndex"
        @update:model-value="updateNodeData('drivePassword', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Password to protect the file download link
      </p>
    </div>

    <div
      v-if="selectedNode.data.driveOperation === 'setTtl'"
      class="space-y-2"
    >
      <Label>TTL (Hours)</Label>
      <Input
        type="number"
        :model-value="selectedNode.data.driveTtlHours ?? ''"
        min="1"
        placeholder="e.g. 24"
        @update:model-value="updateNodeData('driveTtlHours', $event !== '' ? Number($event) : undefined)"
      />
      <p class="text-xs text-muted-foreground">
        Hours until the file download link expires
      </p>
    </div>

    <div
      v-if="selectedNode.data.driveOperation === 'setMaxDownloads'"
      class="space-y-2"
    >
      <Label>Max Downloads</Label>
      <Input
        type="number"
        :model-value="selectedNode.data.driveMaxDownloads ?? ''"
        min="1"
        placeholder="e.g. 5"
        @update:model-value="updateNodeData('driveMaxDownloads', $event !== '' ? Number($event) : undefined)"
      />
      <p class="text-xs text-muted-foreground">
        Maximum number of times the file can be downloaded
      </p>
    </div>

    <div
      v-if="selectedNode.data.driveOperation === 'convertFile'"
      class="space-y-2"
    >
      <Label>Target Format</Label>
      <Select
        :model-value="selectedNode.data.driveConvertTargetFormat || ''"
        :options="driveConvertFormatOptionsFiltered"
        @update:model-value="updateNodeData('driveConvertTargetFormat', $event || undefined)"
      />
      <p class="text-xs text-muted-foreground">
        Format to convert the file to
      </p>
    </div>

    <div class="rounded-lg bg-muted/50 p-3 space-y-1">
      <p class="text-xs font-medium text-foreground">
        Output
      </p>
      <div class="text-xs text-muted-foreground space-y-0.5 font-mono">
        <template v-if="selectedNode.data.driveOperation === 'get'">
          <div>${{ selectedNode.data.label }}.id - file UUID</div>
          <div>${{ selectedNode.data.label }}.filename - file name</div>
          <div>${{ selectedNode.data.label }}.mime_type - MIME type</div>
          <div>${{ selectedNode.data.label }}.size_bytes - file size</div>
          <div>${{ selectedNode.data.label }}.download_url - public download URL</div>
          <div>${{ selectedNode.data.label }}.file_base64 - base64 content (if enabled)</div>
        </template>
        <template v-else-if="selectedNode.data.driveOperation === 'getAll'">
          <div>${{ selectedNode.data.label }}.files - file metadata array</div>
          <div>${{ selectedNode.data.label }}.count - number of files</div>
          <div>${{ selectedNode.data.label }}.files[0].filename - file name</div>
          <div>${{ selectedNode.data.label }}.files[0].size_bytes - file size</div>
          <div>${{ selectedNode.data.label }}.files[0].download_url - public download URL</div>
        </template>
        <template v-else-if="selectedNode.data.driveOperation === 'downloadUrl'">
          <div>${{ selectedNode.data.label }}.id - new file UUID</div>
          <div>${{ selectedNode.data.label }}.filename - file name</div>
          <div>${{ selectedNode.data.label }}.mime_type - MIME type</div>
          <div>${{ selectedNode.data.label }}.size_bytes - file size</div>
          <div>${{ selectedNode.data.label }}.download_url - Drive download URL</div>
        </template>
        <template v-else-if="selectedNode.data.driveOperation === 'save'">
          <div>${{ selectedNode.data.label }}.id - new file UUID</div>
          <div>${{ selectedNode.data.label }}.filename - file name</div>
          <div>${{ selectedNode.data.label }}.mime_type - MIME type</div>
          <div>${{ selectedNode.data.label }}.size_bytes - file size</div>
          <div>${{ selectedNode.data.label }}.download_url - Drive download URL</div>
        </template>
        <template v-else-if="selectedNode.data.driveOperation === 'convertFile'">
          <div>${{ selectedNode.data.label }}.id - new converted file UUID</div>
          <div>${{ selectedNode.data.label }}.filename - converted filename</div>
          <div>${{ selectedNode.data.label }}.mime_type - MIME type</div>
          <div>${{ selectedNode.data.label }}.size_bytes - file size</div>
          <div>${{ selectedNode.data.label }}.download_url - Drive download URL</div>
        </template>
        <template v-else-if="selectedNode.data.driveOperation === 'delete'">
          <div>${{ selectedNode.data.label }}.status - "deleted"</div>
          <div>${{ selectedNode.data.label }}.file_id - deleted file ID</div>
        </template>
        <template v-else-if="selectedNode.data.driveOperation === 'setPassword' || selectedNode.data.driveOperation === 'setTtl' || selectedNode.data.driveOperation === 'setMaxDownloads'">
          <div>${{ selectedNode.data.label }}.status - "updated"</div>
          <div>${{ selectedNode.data.label }}.file_id - file ID</div>
          <div>${{ selectedNode.data.label }}.download_url - new access URL</div>
        </template>
        <template v-else>
          <div>Select an operation to see output fields</div>
        </template>
      </div>
    </div>
  </template>
</template>
