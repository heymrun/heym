<script setup lang="ts">
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";

const {
  selectedNode,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div
      v-if="!['textInput', 'cron', 'sticky', 'errorHandler', 'output', 'throwError', 'telegramTrigger', 'websocketTrigger', 'slackTrigger', 'discordTrigger', 'imapTrigger'].includes(selectedNode.type) && !(selectedNode.type === 'rabbitmq' && selectedNode.data.rabbitmqOperation === 'receive')"
      class="space-y-4 pt-4 border-t"
    >
      <Label class="text-muted-foreground">Error Handling</Label>

      <div class="space-y-3">
        <div class="flex items-center gap-2">
          <input
            id="retry-enabled"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="!!selectedNode.data.retryEnabled"
            @change="updateNodeData('retryEnabled', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="retry-enabled"
            class="text-sm font-normal"
          >
            Retry on failure
          </Label>
        </div>

        <template v-if="selectedNode.data.retryEnabled">
          <div class="space-y-2 pl-6">
            <div class="flex items-center gap-3">
              <Label class="text-sm font-normal min-w-[100px]">Max attempts</Label>
              <Input
                type="number"
                :model-value="selectedNode.data.retryMaxAttempts || 3"
                min="1"
                max="10"
                class="w-20 h-8"
                @update:model-value="updateNodeData('retryMaxAttempts', $event ? parseInt($event as string) : 3)"
              />
            </div>
            <div class="flex items-center gap-3">
              <Label class="text-sm font-normal min-w-[100px]">Wait (seconds)</Label>
              <Input
                type="number"
                :model-value="selectedNode.data.retryWaitSeconds || 5"
                min="1"
                max="60"
                class="w-20 h-8"
                @update:model-value="updateNodeData('retryWaitSeconds', $event ? parseInt($event as string) : 5)"
              />
            </div>
          </div>
          <p class="text-xs text-muted-foreground">
            If node fails, retry up to {{ selectedNode.data.retryMaxAttempts || 3 }} times with {{
              selectedNode.data.retryWaitSeconds || 5 }}s wait between attempts
          </p>
        </template>
      </div>

      <div class="space-y-3 pt-2">
        <div class="flex items-center gap-2">
          <input
            id="on-error-enabled"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="!!selectedNode.data.onErrorEnabled"
            @change="updateNodeData('onErrorEnabled', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="on-error-enabled"
            class="text-sm font-normal"
          >
            Continue on error
          </Label>
        </div>

        <template v-if="selectedNode.data.onErrorEnabled">
          <p class="text-xs text-muted-foreground pl-6">
            When enabled, if this node fails, the workflow will continue via the <span
              class="text-red-400 font-medium"
            >error</span> output handle instead of stopping.
          </p>
          <div class="text-xs font-mono space-y-1 text-muted-foreground pl-6">
            <div>${{ selectedNode.data.label }}.error - Error message</div>
          </div>
        </template>
      </div>
    </div>
  </template>
</template>
