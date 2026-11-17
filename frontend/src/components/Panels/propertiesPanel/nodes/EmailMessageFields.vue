<script setup lang="ts">
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

/** The fields Send Email, Gmail Send and Outlook Send share, To through Attachments. */
withDefaults(defineProps<{ fieldOffset?: number }>(), { fieldOffset: 0 });

const {
  workflowStore,
  sendEmailToInputRef,
  sendEmailCcInputRef,
  sendEmailBccInputRef,
  sendEmailSubjectInputRef,
  sendEmailBodyInputRef,
  sendEmailAttachmentsInputRef,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  exampleRef,
  sendEmailExpressionFieldCount,
  handleSendEmailExpressionFieldNavigate,
  onSendEmailRegisterExpressionFieldIndex,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>To</Label>
      <ExpressionInput
        ref="sendEmailToInputRef"
        :model-value="selectedNode.data.to || ''"
        placeholder="recipient@example.com"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        dialog-title="Edit To"
        navigation-enabled
        :navigation-index="fieldOffset + 0"
        :navigation-total="sendEmailExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="To"
        field-key="to"
        @update:model-value="updateNodeData('to', $event)"
        @navigate="handleSendEmailExpressionFieldNavigate"
        @register-field-index="onSendEmailRegisterExpressionFieldIndex"
      />
      <p class="text-xs text-muted-foreground">
        Recipient email (comma-separated for multiple)
      </p>
    </div>

    <div class="space-y-2">
      <Label>Cc</Label>
      <ExpressionInput
        ref="sendEmailCcInputRef"
        :model-value="selectedNode.data.cc || ''"
        placeholder="cc@example.com"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        dialog-title="Edit Cc"
        navigation-enabled
        :navigation-index="fieldOffset + 1"
        :navigation-total="sendEmailExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Cc"
        field-key="cc"
        @update:model-value="updateNodeData('cc', $event)"
        @navigate="handleSendEmailExpressionFieldNavigate"
        @register-field-index="onSendEmailRegisterExpressionFieldIndex"
      />
      <p class="text-xs text-muted-foreground">
        Carbon copy (comma-separated for multiple)
      </p>
    </div>

    <div class="space-y-2">
      <Label>Bcc</Label>
      <ExpressionInput
        ref="sendEmailBccInputRef"
        :model-value="selectedNode.data.bcc || ''"
        placeholder="bcc@example.com"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        dialog-title="Edit Bcc"
        navigation-enabled
        :navigation-index="fieldOffset + 2"
        :navigation-total="sendEmailExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Bcc"
        field-key="bcc"
        @update:model-value="updateNodeData('bcc', $event)"
        @navigate="handleSendEmailExpressionFieldNavigate"
        @register-field-index="onSendEmailRegisterExpressionFieldIndex"
      />
      <p class="text-xs text-muted-foreground">
        Blind carbon copy, hidden from other recipients
      </p>
    </div>

    <div class="space-y-2">
      <Label>Subject</Label>
      <ExpressionInput
        ref="sendEmailSubjectInputRef"
        :model-value="selectedNode.data.subject || ''"
        placeholder="Email Subject"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        dialog-title="Edit Subject"
        navigation-enabled
        :navigation-index="fieldOffset + 3"
        :navigation-total="sendEmailExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Subject"
        field-key="subject"
        @update:model-value="updateNodeData('subject', $event)"
        @navigate="handleSendEmailExpressionFieldNavigate"
        @register-field-index="onSendEmailRegisterExpressionFieldIndex"
      />
    </div>

    <div class="space-y-2">
      <Label>Body</Label>
      <ExpressionInput
        ref="sendEmailBodyInputRef"
        :model-value="selectedNode.data.emailBody || ''"
        :placeholder="exampleRef"
        :rows="4"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        dialog-title="Edit Email Body"
        navigation-enabled
        :navigation-index="fieldOffset + 4"
        :navigation-total="sendEmailExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Body"
        field-key="emailBody"
        @update:model-value="updateNodeData('emailBody', $event)"
        @navigate="handleSendEmailExpressionFieldNavigate"
        @register-field-index="onSendEmailRegisterExpressionFieldIndex"
      />
      <p class="text-xs text-muted-foreground">
        Use $ expressions like {{ exampleRef }}
      </p>
    </div>

    <div class="space-y-2">
      <Label>Attachments</Label>
      <ExpressionInput
        ref="sendEmailAttachmentsInputRef"
        :model-value="selectedNode.data.attachments || ''"
        placeholder="$drive.id"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        expandable
        dialog-title="Edit Attachments"
        navigation-enabled
        :navigation-index="fieldOffset + 5"
        :navigation-total="sendEmailExpressionFieldCount"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="Attachments"
        field-key="attachments"
        @update:model-value="updateNodeData('attachments', $event)"
        @navigate="handleSendEmailExpressionFieldNavigate"
        @register-field-index="onSendEmailRegisterExpressionFieldIndex"
      />
      <p class="text-xs text-muted-foreground">
        Comma-separated Drive file IDs. Use $ expressions, e.g. an upstream Drive node's id.
      </p>
    </div>
  </template>
</template>
