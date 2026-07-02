<script setup lang="ts">
import { AlertTriangle } from "lucide-vue-next";
import AgentFieldToggle from "@/components/ui/AgentFieldToggle.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  isWorkflowOwner,
  s3BucketExpressionInputRef,
  s3KeyExpressionInputRef,
  s3SourceBucketExpressionInputRef,
  s3SourceKeyExpressionInputRef,
  s3PrefixExpressionInputRef,
  s3ContinuationTokenExpressionInputRef,
  s3BodyExpressionInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  s3ExpressionFieldCount,
  handleS3ExpressionFieldNavigate,
  onS3RegisterExpressionFieldIndex,
  s3CredentialOptions,
  s3OperationOptions,
  s3MaxKeysWarning,
  updateNodeData,
  handleS3MaxKeysChange,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Amazon S3 Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="s3CredentialOptions"
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
      <Select
        :model-value="selectedNode.data.s3Operation || 'putObject'"
        :options="s3OperationOptions"
        @update:model-value="updateNodeData('s3Operation', $event)"
      />
      <p
        v-if="!selectedNode.data.s3Operation"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Operation is required
      </p>
    </div>

    <div
      v-if="selectedNode.data.s3Operation !== 'listBuckets'"
      class="space-y-2"
    >
      <Label>
        <template v-if="selectedNode.data.s3Operation === 'copyObject'">
          Destination Bucket
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'createBucket' || selectedNode.data.s3Operation === 'deleteBucket'">
          Bucket Name
        </template>
        <template v-else>
          Bucket
        </template>
        <span class="text-destructive">*</span>
      </Label>
      <ExpressionInput
        ref="s3BucketExpressionInputRef"
        :model-value="selectedNode.data.s3Bucket || ''"
        placeholder="my-bucket"
        single-line
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        field-key="s3Bucket"
        :navigation-enabled="s3ExpressionFieldCount > 1"
        :navigation-index="0"
        :navigation-total="s3ExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Amazon S3 Bucket"
        @update:model-value="updateNodeData('s3Bucket', $event)"
        @navigate="handleS3ExpressionFieldNavigate"
        @register-field-index="onS3RegisterExpressionFieldIndex"
      />
      <p
        v-if="!selectedNode.data.s3Bucket || selectedNode.data.s3Bucket.trim() === ''"
        class="text-xs text-amber-500 flex items-center gap-1"
      >
        <AlertTriangle class="h-3 w-3" />
        Bucket is required
      </p>
    </div>

    <template v-if="selectedNode.data.s3Operation === 'listBuckets'">
      <p class="text-xs text-muted-foreground">
        Lists all buckets visible to the credential. Requires `s3:ListAllMyBuckets` permission.
      </p>
    </template>

    <template v-else-if="selectedNode.data.s3Operation === 'createBucket'">
      <p class="text-xs text-muted-foreground">
        Creates the bucket in the credential region. Requires `s3:CreateBucket` permission.
      </p>
    </template>

    <template v-else-if="selectedNode.data.s3Operation === 'deleteBucket'">
      <p class="text-xs text-muted-foreground">
        Deletes an empty bucket. Requires `s3:DeleteBucket` permission. Remove all objects first.
      </p>
    </template>

    <template v-else-if="selectedNode.data.s3Operation === 'listObjects'">
      <div class="space-y-2">
        <Label>Prefix</Label>
        <ExpressionInput
          ref="s3PrefixExpressionInputRef"
          :model-value="selectedNode.data.s3Prefix || ''"
          placeholder="docs/"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="s3Prefix"
          :navigation-enabled="s3ExpressionFieldCount > 1"
          :navigation-index="1"
          :navigation-total="s3ExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Amazon S3 Prefix"
          @update:model-value="updateNodeData('s3Prefix', $event)"
          @navigate="handleS3ExpressionFieldNavigate"
          @register-field-index="onS3RegisterExpressionFieldIndex"
        />
      </div>
      <div class="space-y-2">
        <div class="flex items-center justify-between gap-2">
          <Label>Max Keys</Label>
          <AgentFieldToggle
            :node-id="selectedNode.id"
            field-key="s3MaxKeys"
          />
        </div>
        <Input
          :model-value="selectedNode.data.s3MaxKeys || '100'"
          type="number"
          min="1"
          max="1000"
          @update:model-value="handleS3MaxKeysChange($event)"
        />
        <p
          v-if="s3MaxKeysWarning"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          {{ s3MaxKeysWarning }}
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Maximum number of objects to return per page (1–1000). Use Continuation Token to fetch the next page.
        </p>
      </div>
      <div class="space-y-2">
        <Label>Continuation Token</Label>
        <ExpressionInput
          ref="s3ContinuationTokenExpressionInputRef"
          :model-value="selectedNode.data.s3ContinuationToken || ''"
          placeholder="Leave empty for first page; use $previousNode.next_continuation_token"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="s3ContinuationToken"
          :navigation-enabled="s3ExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="s3ExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Amazon S3 Continuation Token"
          @update:model-value="updateNodeData('s3ContinuationToken', $event)"
          @navigate="handleS3ExpressionFieldNavigate"
          @register-field-index="onS3RegisterExpressionFieldIndex"
        />
        <p class="text-xs text-muted-foreground">
          Optional. Pass the previous response's <span class="font-mono">next_continuation_token</span> to list the next page (n8n limit-mode pagination).
        </p>
      </div>
    </template>

    <template v-else-if="selectedNode.data.s3Operation === 'createFolder' || selectedNode.data.s3Operation === 'deleteFolder' || selectedNode.data.s3Operation === 'getAllFolder'">
      <div class="space-y-2">
        <Label>Folder Path <span class="text-destructive">*</span></Label>
        <ExpressionInput
          ref="s3KeyExpressionInputRef"
          :model-value="selectedNode.data.s3Key || ''"
          placeholder="docs/archive"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="s3Key"
          :navigation-enabled="s3ExpressionFieldCount > 1"
          :navigation-index="1"
          :navigation-total="s3ExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Amazon S3 Folder Path"
          @update:model-value="updateNodeData('s3Key', $event)"
          @navigate="handleS3ExpressionFieldNavigate"
          @register-field-index="onS3RegisterExpressionFieldIndex"
        />
        <p
          v-if="!selectedNode.data.s3Key || selectedNode.data.s3Key.trim() === ''"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          Folder path is required
        </p>
        <p
          v-else-if="selectedNode.data.s3Operation === 'createFolder'"
          class="text-xs text-muted-foreground"
        >
          Creates a zero-byte folder marker. A trailing `/` is added automatically.
        </p>
        <p
          v-else-if="selectedNode.data.s3Operation === 'deleteFolder'"
          class="text-xs text-muted-foreground"
        >
          Deletes all objects under this prefix, including nested files and subfolders.
        </p>
        <p
          v-else
          class="text-xs text-muted-foreground"
        >
          Lists all object metadata under this prefix (paginated server-side).
        </p>
      </div>
    </template>

    <template v-else-if="selectedNode.data.s3Operation === 'copyObject'">
      <div class="space-y-2">
        <Label>Source Bucket</Label>
        <ExpressionInput
          ref="s3SourceBucketExpressionInputRef"
          :model-value="selectedNode.data.s3SourceBucket || ''"
          placeholder="Leave empty to use destination bucket"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="s3SourceBucket"
          :navigation-enabled="s3ExpressionFieldCount > 1"
          :navigation-index="1"
          :navigation-total="s3ExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Amazon S3 Source Bucket"
          @update:model-value="updateNodeData('s3SourceBucket', $event)"
          @navigate="handleS3ExpressionFieldNavigate"
          @register-field-index="onS3RegisterExpressionFieldIndex"
        />
      </div>
      <div class="space-y-2">
        <Label>Source Object Key <span class="text-destructive">*</span></Label>
        <ExpressionInput
          ref="s3SourceKeyExpressionInputRef"
          :model-value="selectedNode.data.s3SourceKey || ''"
          placeholder="docs/source.txt"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="s3SourceKey"
          :navigation-enabled="s3ExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="s3ExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Amazon S3 Source Object Key"
          @update:model-value="updateNodeData('s3SourceKey', $event)"
          @navigate="handleS3ExpressionFieldNavigate"
          @register-field-index="onS3RegisterExpressionFieldIndex"
        />
        <p
          v-if="!selectedNode.data.s3SourceKey || selectedNode.data.s3SourceKey.trim() === ''"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          Source object key is required for copy operation
        </p>
      </div>
      <div class="space-y-2">
        <Label>Destination Object Key <span class="text-destructive">*</span></Label>
        <ExpressionInput
          ref="s3KeyExpressionInputRef"
          :model-value="selectedNode.data.s3Key || ''"
          placeholder="archive/source.txt"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="s3Key"
          :navigation-enabled="s3ExpressionFieldCount > 1"
          :navigation-index="3"
          :navigation-total="s3ExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Amazon S3 Destination Object Key"
          @update:model-value="updateNodeData('s3Key', $event)"
          @navigate="handleS3ExpressionFieldNavigate"
          @register-field-index="onS3RegisterExpressionFieldIndex"
        />
        <p
          v-if="!selectedNode.data.s3Key || selectedNode.data.s3Key.trim() === ''"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          Destination object key is required for copy operation
        </p>
      </div>
    </template>

    <template v-else>
      <div class="space-y-2">
        <Label>Object Key <span class="text-destructive">*</span></Label>
        <ExpressionInput
          ref="s3KeyExpressionInputRef"
          :model-value="selectedNode.data.s3Key || ''"
          placeholder="docs/report.txt"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="s3Key"
          :navigation-enabled="s3ExpressionFieldCount > 1"
          :navigation-index="1"
          :navigation-total="s3ExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Amazon S3 Object Key"
          @update:model-value="updateNodeData('s3Key', $event)"
          @navigate="handleS3ExpressionFieldNavigate"
          @register-field-index="onS3RegisterExpressionFieldIndex"
        />
        <p
          v-if="!selectedNode.data.s3Key || selectedNode.data.s3Key.trim() === ''"
          class="text-xs text-amber-500 flex items-center gap-1"
        >
          <AlertTriangle class="h-3 w-3" />
          Object key is required for this operation
        </p>
      </div>

      <div
        v-if="selectedNode.data.s3Operation === 'putObject'"
        class="space-y-2"
      >
        <Label>Body</Label>
        <ExpressionInput
          ref="s3BodyExpressionInputRef"
          :model-value="selectedNode.data.s3Body || ''"
          placeholder="$input.text"
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="s3Body"
          :navigation-enabled="s3ExpressionFieldCount > 1"
          :navigation-index="2"
          :navigation-total="s3ExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Amazon S3 Object Body"
          @update:model-value="updateNodeData('s3Body', $event)"
          @navigate="handleS3ExpressionFieldNavigate"
          @register-field-index="onS3RegisterExpressionFieldIndex"
        />
      </div>

      <div
        v-if="selectedNode.data.s3Operation === 'putObject'"
        class="space-y-2"
      >
        <Label>Content Type</Label>
        <ExpressionInput
          :model-value="selectedNode.data.s3ContentType || ''"
          placeholder="text/plain"
          single-line
          :nodes="workflowStore.nodes"
          :node-results="workflowStore.nodeResults"
          :edges="workflowStore.edges"
          :current-node-id="selectedNode.id"
          field-key="s3ContentType"
          :navigation-enabled="s3ExpressionFieldCount > 1"
          :navigation-index="3"
          :navigation-total="s3ExpressionFieldCount"
          :dialog-node-label="selectedNodeEvaluateDialogLabel"
          dialog-key-label="Amazon S3 Content Type"
          @update:model-value="updateNodeData('s3ContentType', $event)"
          @navigate="handleS3ExpressionFieldNavigate"
          @register-field-index="onS3RegisterExpressionFieldIndex"
        />
      </div>

      <div
        v-if="selectedNode.data.s3Operation === 'getObject'"
        class="space-y-2"
      >
        <Label>Options</Label>
        <div class="flex items-center gap-2">
          <input
            id="s3-include-binary"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="!!selectedNode.data.s3IncludeBinary"
            @change="updateNodeData('s3IncludeBinary', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="s3-include-binary"
            class="font-normal text-sm"
          >
            Return binary as base64
          </Label>
        </div>
      </div>
    </template>

    <div class="rounded-lg bg-muted/50 p-3 space-y-1">
      <p class="text-xs font-medium text-foreground">
        Output
      </p>
      <div class="text-xs text-muted-foreground space-y-0.5 font-mono">
        <template v-if="selectedNode.data.s3Operation === 'putObject'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
          <div>${{ selectedNode.data.label }}.key - object key</div>
          <div>${{ selectedNode.data.label }}.etag - uploaded object etag</div>
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'getObject'">
          <div>${{ selectedNode.data.label }}.content_type - MIME type</div>
          <div>${{ selectedNode.data.label }}.content_length - byte size</div>
          <div>${{ selectedNode.data.label }}.body_text - decoded text body</div>
          <div>${{ selectedNode.data.label }}.body_base64 - base64 body when enabled</div>
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'listObjects'">
          <div>${{ selectedNode.data.label }}.objects - object metadata array</div>
          <div>${{ selectedNode.data.label }}.count - number of returned objects</div>
          <div>${{ selectedNode.data.label }}.truncated - more pages available</div>
          <div>${{ selectedNode.data.label }}.next_continuation_token - token for next page</div>
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'deleteObject'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
          <div>${{ selectedNode.data.label }}.key - object key</div>
          <div>${{ selectedNode.data.label }}.delete_marker - delete marker flag</div>
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'createBucket'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
          <div>${{ selectedNode.data.label }}.region - bucket region</div>
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'deleteBucket'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'createFolder'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
          <div>${{ selectedNode.data.label }}.folder - folder key ending with /</div>
          <div>${{ selectedNode.data.label }}.etag - folder marker etag</div>
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'deleteFolder'">
          <div>${{ selectedNode.data.label }}.success - Boolean</div>
          <div>${{ selectedNode.data.label }}.bucket - bucket name</div>
          <div>${{ selectedNode.data.label }}.folder - folder prefix</div>
          <div>${{ selectedNode.data.label }}.deleted_count - number of deleted objects</div>
          <div>${{ selectedNode.data.label }}.deleted_keys - deleted object keys</div>
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'getAllFolder'">
          <div>${{ selectedNode.data.label }}.folder - folder prefix</div>
          <div>${{ selectedNode.data.label }}.count - number of objects</div>
          <div>${{ selectedNode.data.label }}.objects - object metadata array</div>
          <div>${{ selectedNode.data.label }}.objects[0].key - first object key</div>
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'listBuckets'">
          <div>${{ selectedNode.data.label }}.buckets - bucket metadata array</div>
          <div>${{ selectedNode.data.label }}.count - number of buckets</div>
          <div>${{ selectedNode.data.label }}.buckets[0].name - bucket name</div>
        </template>
        <template v-else-if="selectedNode.data.s3Operation === 'copyObject'">
          <div>${{ selectedNode.data.label }}.source_bucket - source bucket</div>
          <div>${{ selectedNode.data.label }}.source_key - source object key</div>
          <div>${{ selectedNode.data.label }}.bucket - destination bucket</div>
          <div>${{ selectedNode.data.label }}.key - destination object key</div>
          <div>${{ selectedNode.data.label }}.etag - copied object etag</div>
        </template>
      </div>
    </div>
  </template>
</template>
