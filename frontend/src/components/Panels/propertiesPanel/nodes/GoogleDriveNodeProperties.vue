<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import SearchableSelect from "@/components/ui/SearchableSelect.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  isWorkflowOwner,
  googleDriveFolderIdExpressionInputRef,
  googleDriveFileIdExpressionInputRef,
  googleDriveMaxResultsExpressionInputRef,
  googleDriveQueryExpressionInputRef,
  googleDriveFilenameExpressionInputRef,
  googleDriveContentExpressionInputRef,
  googleDriveNewNameExpressionInputRef,
  googleDriveNewParentExpressionInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  googleDriveExpressionFieldCount,
  handleGoogleDriveExpressionFieldNavigate,
  onGoogleDriveRegisterExpressionFieldIndex,
  googleDriveCredentialOptions,
  googleDriveOperationOptions,
  googleDriveExportFormatOptions,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Google Drive Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="googleDriveCredentialOptions"
        :disabled="!isWorkflowOwner"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <div v-if="!selectedNode.data.credentialId">
        <p class="text-xs text-amber-500 flex items-center gap-1">
          <AlertTriangle class="h-3 w-3" />
          Credential is required.
        </p>
        <p class="text-xs text-muted-foreground mt-1">
          <a
            href="/?tab=credentials"
            class="text-primary hover:underline"
            @click.prevent="$router.push('/?tab=credentials')"
          >Add credentials</a> in Dashboard
        </p>
      </div>
    </div>

    <div class="space-y-2">
      <Label>Operation</Label>
      <SearchableSelect
        :model-value="selectedNode.data.gdOperation || ''"
        :options="googleDriveOperationOptions"
        search-placeholder="Search Google Drive operations..."
        @update:model-value="updateNodeData('gdOperation', $event)"
      />
    </div>

    <template v-if="selectedNode.data.gdOperation">
      <!-- Folder-targeted operations -->
      <div
        v-if="['listFolderFiles', 'removeFolder'].includes(selectedNode.data.gdOperation)"
        class="space-y-2"
      >
        <Label>Folder ID or URL</Label>
        <ExpressionInput
          ref="googleDriveFolderIdExpressionInputRef"
          :model-value="selectedNode.data.gdFolderId || ''"
          placeholder="1FolderXyz or https://drive.google.com/drive/folders/..."
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="googleDriveExpressionFieldCount > 1"
          :navigation-index="0"
          :navigation-total="googleDriveExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Folder ID or URL"
          field-key="gdFolderId"
          @navigate="handleGoogleDriveExpressionFieldNavigate"
          @register-field-index="onGoogleDriveRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gdFolderId', $event)"
        />
        <p
          v-if="selectedNode.data.gdOperation === 'listFolderFiles'"
          class="text-xs text-muted-foreground"
        >
          Leave empty to list the Drive root.
        </p>
      </div>

      <!-- File-targeted operations -->
      <div
        v-if="
          ['downloadFile', 'syncToHeymDrive', 'updateFile', 'removeFile'].includes(
            selectedNode.data.gdOperation,
          )
        "
        class="space-y-2"
      >
        <Label>File ID or URL</Label>
        <ExpressionInput
          ref="googleDriveFileIdExpressionInputRef"
          :model-value="selectedNode.data.gdFileId || ''"
          placeholder="1AbCdEf or https://drive.google.com/file/d/.../view"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="googleDriveExpressionFieldCount > 1"
          :navigation-index="0"
          :navigation-total="googleDriveExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="File ID or URL"
          field-key="gdFileId"
          @navigate="handleGoogleDriveExpressionFieldNavigate"
          @register-field-index="onGoogleDriveRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gdFileId', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Accepts a full Drive or Docs URL, or a bare file ID.
        </p>
      </div>

      <!-- listFolderFiles extras -->
      <template v-if="selectedNode.data.gdOperation === 'listFolderFiles'">
        <div class="space-y-2">
          <Label>Max Results</Label>
          <ExpressionInput
            ref="googleDriveMaxResultsExpressionInputRef"
            :model-value="selectedNode.data.gdMaxResults || '100'"
            placeholder="100"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :navigation-enabled="googleDriveExpressionFieldCount > 1"
            :navigation-index="1"
            :navigation-total="googleDriveExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Max results"
            field-key="gdMaxResults"
            @navigate="handleGoogleDriveExpressionFieldNavigate"
            @register-field-index="onGoogleDriveRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('gdMaxResults', $event)"
          />
        </div>

        <div class="space-y-2">
          <Label>Filter Query (optional)</Label>
          <ExpressionInput
            ref="googleDriveQueryExpressionInputRef"
            :model-value="selectedNode.data.gdQuery || ''"
            placeholder="mimeType='application/pdf'"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :navigation-enabled="googleDriveExpressionFieldCount > 1"
            :navigation-index="2"
            :navigation-total="googleDriveExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Filter query"
            field-key="gdQuery"
            @navigate="handleGoogleDriveExpressionFieldNavigate"
            @register-field-index="onGoogleDriveRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('gdQuery', $event)"
          />
          <p class="text-xs text-muted-foreground">
            Google Drive query syntax, combined with the folder filter.
          </p>
        </div>

        <div class="flex items-center gap-2 pt-1">
          <input
            id="gd-include-trashed"
            type="checkbox"
            :checked="selectedNode.data.gdIncludeTrashed === true"
            class="rounded border-border"
            @change="updateNodeData('gdIncludeTrashed', ($event.target as HTMLInputElement).checked)"
          >
          <label
            for="gd-include-trashed"
            class="text-xs cursor-pointer select-none"
          >Include trashed files</label>
        </div>
      </template>

      <!-- Export format for download-shaped operations -->
      <div
        v-if="['downloadFile', 'syncToHeymDrive'].includes(selectedNode.data.gdOperation)"
        class="space-y-2"
      >
        <Label>Export Format</Label>
        <Select
          :model-value="selectedNode.data.gdExportFormat || ''"
          :options="googleDriveExportFormatOptions"
          @update:model-value="updateNodeData('gdExportFormat', $event)"
        />
        <p class="text-xs text-muted-foreground">
          Applies to Google Docs, Sheets, and Slides, which have no downloadable bytes and must be
          exported. Ignored for regular files.
        </p>
      </div>

      <!-- syncToHeymDrive extras -->
      <div
        v-if="selectedNode.data.gdOperation === 'syncToHeymDrive'"
        class="space-y-2"
      >
        <Label>Heym Drive Filename (optional)</Label>
        <ExpressionInput
          ref="googleDriveFilenameExpressionInputRef"
          :model-value="selectedNode.data.gdFilename || ''"
          placeholder="Leave empty to keep the Google Drive name"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          :navigation-enabled="googleDriveExpressionFieldCount > 1"
          :navigation-index="1"
          :navigation-total="googleDriveExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Heym Drive filename"
          field-key="gdFilename"
          @navigate="handleGoogleDriveExpressionFieldNavigate"
          @register-field-index="onGoogleDriveRegisterExpressionFieldIndex"
          @update:model-value="updateNodeData('gdFilename', $event)"
        />
      </div>

      <!-- updateFile extras -->
      <template v-if="selectedNode.data.gdOperation === 'updateFile'">
        <div class="space-y-2">
          <Label>New Content (base64, optional)</Label>
          <ExpressionInput
            ref="googleDriveContentExpressionInputRef"
            :model-value="selectedNode.data.gdBase64Content || ''"
            placeholder="$PreviousNode.content_base64"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :navigation-enabled="googleDriveExpressionFieldCount > 1"
            :navigation-index="1"
            :navigation-total="googleDriveExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="New content"
            field-key="gdBase64Content"
            @navigate="handleGoogleDriveExpressionFieldNavigate"
            @register-field-index="onGoogleDriveRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('gdBase64Content', $event)"
          />
        </div>

        <div class="space-y-2">
          <Label>New Name (optional)</Label>
          <ExpressionInput
            ref="googleDriveNewNameExpressionInputRef"
            :model-value="selectedNode.data.gdNewName || ''"
            placeholder="renamed.pdf"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :navigation-enabled="googleDriveExpressionFieldCount > 1"
            :navigation-index="2"
            :navigation-total="googleDriveExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="New name"
            field-key="gdNewName"
            @navigate="handleGoogleDriveExpressionFieldNavigate"
            @register-field-index="onGoogleDriveRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('gdNewName', $event)"
          />
        </div>

        <div class="space-y-2">
          <Label>Move to Folder (optional)</Label>
          <ExpressionInput
            ref="googleDriveNewParentExpressionInputRef"
            :model-value="selectedNode.data.gdNewParentId || ''"
            placeholder="1DestinationFolderId or folder URL"
            :nodes="workflowStore.nodes"
            :node-results="workflowStore.nodeResults"
            :edges="workflowStore.edges"
            :current-node-id="selectedNode.id"
            :navigation-enabled="googleDriveExpressionFieldCount > 1"
            :navigation-index="3"
            :navigation-total="googleDriveExpressionFieldCount"
            :dialog-node-label="selectedNodeEvaluateDialogLabel"
            dialog-key-label="Move to folder"
            field-key="gdNewParentId"
            @navigate="handleGoogleDriveExpressionFieldNavigate"
            @register-field-index="onGoogleDriveRegisterExpressionFieldIndex"
            @update:model-value="updateNodeData('gdNewParentId', $event)"
          />
        </div>

        <p class="text-xs text-muted-foreground">
          Fill at least one of the three. Fields left empty are not changed.
        </p>
      </template>

      <!-- Delete safety -->
      <template v-if="['removeFile', 'removeFolder'].includes(selectedNode.data.gdOperation)">
        <div class="flex items-center gap-2 pt-1">
          <input
            id="gd-permanent-delete"
            type="checkbox"
            :checked="selectedNode.data.gdPermanentDelete === true"
            class="rounded border-border"
            @change="updateNodeData('gdPermanentDelete', ($event.target as HTMLInputElement).checked)"
          >
          <label
            for="gd-permanent-delete"
            class="text-xs cursor-pointer select-none"
          >Delete permanently</label>
        </div>
        <p
          v-if="selectedNode.data.gdPermanentDelete"
          class="text-xs text-amber-500 flex items-start gap-1"
        >
          <AlertTriangle class="h-3 w-3 mt-0.5 shrink-0" />
          <span v-if="selectedNode.data.gdOperation === 'removeFolder'">
            The folder and everything inside it will be destroyed and cannot be recovered.
          </span>
          <span v-else>This file will be destroyed and cannot be recovered.</span>
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          The item is moved to Google Drive trash and can be restored.
        </p>
      </template>
    </template>
  </template>
</template>
