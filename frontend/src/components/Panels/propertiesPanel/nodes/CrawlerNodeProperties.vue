<script setup lang="ts">
import { AlertTriangle, MousePointerClick, Plus, Trash2 } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  crawlerUrlInputRef,
  openSelectorPickerCrawler,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  crawlerCredentialOptions,
  crawlerModeOptions,
  addCrawlerSelector,
  removeCrawlerSelector,
  updateCrawlerSelector,
  updateCrawlerSelectorAttributes,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-2">
      <Label>Credential</Label>
      <Select
        :model-value="selectedNode.data.credentialId || ''"
        :options="crawlerCredentialOptions"
        @update:model-value="updateNodeData('credentialId', $event)"
      />
      <div v-if="!selectedNode.data.credentialId">
        <p class="text-xs text-amber-500 flex items-center gap-1">
          <AlertTriangle class="h-3 w-3" />
          Select a FlareSolverr credential
        </p>
      </div>
    </div>

    <div class="space-y-2">
      <Label>URL to Crawl <span class="text-destructive">*</span></Label>
      <ExpressionInput
        ref="crawlerUrlInputRef"
        :model-value="selectedNode.data.crawlerUrl || ''"
        placeholder="https://example.com or $input.text"
        :rows="1"
        :nodes="workflowStore.nodes"
        :node-results="workflowStore.nodeResults"
        :edges="workflowStore.edges"
        :current-node-id="selectedNode.id"
        :dialog-node-label="selectedNodeEvaluateDialogLabel"
        dialog-key-label="URL to crawl"
        field-key="crawlerUrl"
        @update:model-value="updateNodeData('crawlerUrl', $event)"
      />
      <p class="text-xs text-muted-foreground">
        URL to scrape (supports expressions)
      </p>
    </div>

    <div class="space-y-2">
      <Label>Wait (seconds)</Label>
      <Input
        type="number"
        :model-value="selectedNode.data.crawlerWaitSeconds || 0"
        placeholder="0"
        min="0"
        max="60"
        @update:model-value="updateNodeData('crawlerWaitSeconds', $event ? parseInt($event as string) : 0)"
      />
      <p class="text-xs text-muted-foreground">
        Wait time before extracting content (for dynamic pages)
      </p>
    </div>

    <div class="space-y-2">
      <Label>Max Timeout (ms)</Label>
      <Input
        type="number"
        :model-value="selectedNode.data.crawlerMaxTimeout || 60000"
        placeholder="60000"
        min="1000"
        max="300000"
        @update:model-value="updateNodeData('crawlerMaxTimeout', $event ? parseInt($event as string) : 60000)"
      />
      <p class="text-xs text-muted-foreground">
        Maximum timeout for the request in milliseconds
      </p>
    </div>

    <div class="space-y-2">
      <Label>Mode</Label>
      <Select
        :model-value="selectedNode.data.crawlerMode || 'basic'"
        :options="crawlerModeOptions"
        @update:model-value="updateNodeData('crawlerMode', $event)"
      />
      <p class="text-xs text-muted-foreground">
        Basic returns raw HTML, Extract parses with CSS selectors
      </p>
    </div>

    <template v-if="selectedNode.data.crawlerMode === 'extract'">
      <div class="space-y-2 pt-2 border-t">
        <div class="flex items-center justify-between">
          <Label>CSS Selectors</Label>
          <Button
            variant="outline"
            size="sm"
            class="h-7 text-xs"
            @click="addCrawlerSelector"
          >
            <Plus class="h-3 w-3 mr-1" />
            Add Selector
          </Button>
        </div>

        <div
          v-for="(selector, index) in (selectedNode.data.crawlerSelectors || [])"
          :key="index"
          class="space-y-2 p-3 border rounded-md bg-muted/30"
        >
          <div class="flex items-center justify-between">
            <span class="text-xs font-medium">Selector {{ index + 1 }}</span>
            <Button
              variant="ghost"
              size="sm"
              class="h-6 w-6 p-0 text-destructive hover:text-destructive"
              @click="removeCrawlerSelector(index)"
            >
              <Trash2 class="h-3 w-3" />
            </Button>
          </div>

          <div class="space-y-1">
            <Label class="text-xs">Name</Label>
            <Input
              :model-value="selector.name"
              placeholder="items"
              @update:model-value="updateCrawlerSelector(index, 'name', $event as string)"
            />
          </div>

          <div class="space-y-1">
            <div class="flex items-center justify-between gap-2">
              <Label class="text-xs">CSS Selector</Label>
              <Button
                variant="ghost"
                size="sm"
                class="h-6 gap-1 text-xs"
                @click="openSelectorPickerCrawler(index)"
              >
                <MousePointerClick class="h-3 w-3" />
                Pick from page
              </Button>
            </div>
            <Input
              :model-value="selector.selector"
              placeholder="ul#timeline > li"
              @update:model-value="updateCrawlerSelector(index, 'selector', $event as string)"
            />
          </div>

          <div class="space-y-1">
            <Label class="text-xs">Attributes (comma-separated)</Label>
            <Input
              :model-value="(selector.attributes || []).join(', ')"
              placeholder="data-post-id, href, class"
              @update:model-value="updateCrawlerSelectorAttributes(index, $event as string)"
            />
            <p class="text-xs text-muted-foreground">
              HTML attributes to extract from each element
            </p>
          </div>
        </div>

        <p
          v-if="!selectedNode.data.crawlerSelectors?.length"
          class="text-xs text-muted-foreground"
        >
          Add CSS selectors to extract specific elements from the page
        </p>
      </div>
    </template>

    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Output</Label>
      <div class="text-xs font-mono space-y-1 text-muted-foreground">
        <div>${{ selectedNode.data.label }}.html - Raw HTML content</div>
        <div>${{ selectedNode.data.label }}.url - Crawled URL</div>
        <div>${{ selectedNode.data.label }}.status - Response status</div>
        <template v-if="selectedNode.data.crawlerMode === 'extract'">
          <div>${{ selectedNode.data.label }}.extracted - Extracted data by selector name</div>
        </template>
      </div>
    </div>
  </template>
</template>
