<script setup lang="ts">
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";
import EmailMessageFields from "./EmailMessageFields.vue";

const { selectedNode, smtpCredentialOptions, updateNodeData } = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>SMTP Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="smtpCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <p
        v-if="!selectedNode.data.credentialId"
        class="text-xs text-muted-foreground"
      >
        <a
          href="/?tab=credentials"
          class="text-primary hover:underline"
          @click.prevent="$router.push('/?tab=credentials')"
        >Add credentials</a> in Dashboard
      </p>
    </div>

    <EmailMessageFields />
  </template>
</template>
