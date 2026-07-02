<script setup lang="ts">
import { ChevronDown, ChevronRight, MousePointerClick, Plus, Trash2 } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import ExpressionInput from "@/components/ui/ExpressionInput.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import Select from "@/components/ui/Select.vue";
import type { PlaywrightStepAction } from "@/types/workflow";
import { usePropertiesPanelContext } from "../usePropertiesPanelController";

const {
  workflowStore,
  expandedSavedStepKey,
  openSelectorPickerPlaywright,
  selectedNode,
  selectedNodeEvaluateDialogLabel,
  credentialOptions,
  playwrightStepActionOptions,
  loadPlaywrightAiStepModels,
  playwrightAiStepModelOptions,
  playwrightStepSections,
  getPlaywrightSteps,
  savedStepKey,
  addPlaywrightStep,
  removePlaywrightStep,
  movePlaywrightStepUp,
  movePlaywrightStepDown,
  playwrightStepDialogKey,
  playwrightStepActionLabel,
  playwrightExpressionNavPlan,
  playwrightExprNavGlobalIndexForAuthState,
  playwrightExprNavGlobalIndexForAuthSelector,
  playwrightExprNavGlobalIndexForStep,
  bindPlaywrightExprSlotRef,
  handlePlaywrightExpressionFieldNavigate,
  onPlaywrightRegisterExpressionFieldIndex,
  updatePlaywrightStep,
  updatePlaywrightStepSavedStep,
  removePlaywrightStepSavedStep,
  formatSavedStep,
  updateNodeData,
} = usePropertiesPanelContext();
</script>

<template>
  <template v-if="selectedNode">
    <div class="space-y-4">
      <div class="space-y-2">
        <Label class="text-muted-foreground">Auth & Session</Label>
        <div class="flex items-center gap-2">
          <input
            id="playwright-auth-enabled"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="selectedNode.data.playwrightAuthEnabled === true"
            @change="updateNodeData('playwrightAuthEnabled', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="playwright-auth-enabled"
            class="text-sm font-normal"
          >
            Restore session from cookies/storageState
          </Label>
        </div>
        <p class="text-xs text-muted-foreground">
          Load session data from an expression like <code class="font-mono">$global.authState</code>, verify
          login with a selector, and run fallback login steps only when needed.
        </p>

        <div
          v-if="selectedNode.data.playwrightAuthEnabled"
          class="space-y-3 rounded-md border border-border/60 bg-muted/20 p-3"
        >
          <div class="space-y-1">
            <Label class="text-xs">Auth state expression</Label>
            <ExpressionInput
              :ref="(el) => bindPlaywrightExprSlotRef('authState', el)"
              :model-value="selectedNode.data.playwrightAuthStateExpression || ''"
              placeholder="$global.authState or [{&quot;name&quot;:&quot;session&quot;,...}]"
              :rows="2"
              :nodes="workflowStore.nodes"
              :node-results="workflowStore.nodeResults"
              :edges="workflowStore.edges"
              :current-node-id="selectedNode.id"
              :dialog-node-label="selectedNodeEvaluateDialogLabel"
              dialog-key-label="Playwright auth · state expression"
              :navigation-enabled="playwrightExpressionNavPlan.total > 1"
              :navigation-index="playwrightExprNavGlobalIndexForAuthState()"
              :navigation-total="playwrightExpressionNavPlan.total"
              @navigate="handlePlaywrightExpressionFieldNavigate"
              @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
              @update:model-value="updateNodeData('playwrightAuthStateExpression', $event)"
            />
            <p class="text-xs text-muted-foreground">
              Accepts a Playwright <code class="font-mono">storageState</code> object or a raw
              <code class="font-mono">cookies[]</code> array, including JSON strings of either.
            </p>
          </div>

          <div class="space-y-1">
            <Label class="text-xs">Authenticated selector</Label>
            <ExpressionInput
              :ref="(el) => bindPlaywrightExprSlotRef('authSelector', el)"
              :model-value="selectedNode.data.playwrightAuthCheckSelector || ''"
              placeholder="nav [data-user-menu] or text=Dashboard"
              :rows="1"
              :nodes="workflowStore.nodes"
              :node-results="workflowStore.nodeResults"
              :edges="workflowStore.edges"
              :current-node-id="selectedNode.id"
              :dialog-node-label="selectedNodeEvaluateDialogLabel"
              dialog-key-label="Playwright auth · check selector"
              :navigation-enabled="playwrightExpressionNavPlan.total > 1"
              :navigation-index="playwrightExprNavGlobalIndexForAuthSelector()"
              :navigation-total="playwrightExpressionNavPlan.total"
              @navigate="handlePlaywrightExpressionFieldNavigate"
              @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
              @update:model-value="updateNodeData('playwrightAuthCheckSelector', $event)"
            />
            <p class="text-xs text-muted-foreground">
              The selector must be visible after the first navigate step. If not, fallback login steps run.
            </p>
          </div>

          <div class="space-y-1">
            <Label class="text-xs">Auth check timeout (ms)</Label>
            <Input
              type="number"
              :model-value="selectedNode.data.playwrightAuthCheckTimeout || 5000"
              placeholder="5000"
              min="1"
              @update:model-value="updateNodeData('playwrightAuthCheckTimeout', $event ? parseInt($event as string) : 5000)"
            />
          </div>
        </div>
      </div>

      <div
        v-for="section in playwrightStepSections"
        :key="section.key"
        class="space-y-2"
      >
        <div class="flex items-center justify-between gap-3">
          <div class="space-y-0.5">
            <Label>{{ section.label }}</Label>
            <p
              v-if="section.helpText"
              class="text-xs text-muted-foreground"
            >
              {{ section.helpText }}
            </p>
          </div>
          <Button
            variant="outline"
            size="sm"
            class="h-7 text-xs"
            @click="addPlaywrightStep(section.key)"
          >
            <Plus class="h-3 w-3 mr-1" />
            Add Step
          </Button>
        </div>

        <div
          v-for="(step, index) in getPlaywrightSteps(section.key)"
          :key="`${section.key}-${index}`"
          :data-playwright-step="section.key"
          class="space-y-2 p-3 border rounded-md bg-muted/30"
        >
          <div class="flex items-center justify-between gap-2">
            <span class="text-xs font-medium">Step {{ index + 1 }}</span>
            <div class="flex items-center gap-1">
              <Button
                variant="outline"
                size="sm"
                class="h-7 w-7 p-0 shrink-0 text-base font-semibold leading-none text-muted-foreground hover:text-foreground"
                aria-label="Move step up"
                :disabled="index === 0"
                @click="movePlaywrightStepUp(section.key, index)"
              >
                ↑
              </Button>
              <Button
                variant="outline"
                size="sm"
                class="h-7 w-7 p-0 shrink-0 text-base font-semibold leading-none text-muted-foreground hover:text-foreground"
                aria-label="Move step down"
                :disabled="index >= getPlaywrightSteps(section.key).length - 1"
                @click="movePlaywrightStepDown(section.key, index)"
              >
                ↓
              </Button>
              <Button
                variant="ghost"
                size="sm"
                class="h-7 gap-1.5 text-destructive hover:bg-destructive/10 hover:text-destructive"
                aria-label="Remove step"
                @click="removePlaywrightStep(section.key, index)"
              >
                <Trash2 class="h-3.5 w-3.5" />
                Remove
              </Button>
            </div>
          </div>

          <div class="space-y-1">
            <Label class="text-xs">Action</Label>
            <Select
              :model-value="step.action"
              :options="playwrightStepActionOptions"
              @update:model-value="updatePlaywrightStep(section.key, index, 'action', $event as PlaywrightStepAction)"
            />
          </div>

          <template v-if="step.action === 'navigate'">
            <div class="space-y-1">
              <Label class="text-xs">URL</Label>
              <ExpressionInput
                :ref="(el) => bindPlaywrightExprSlotRef(`${section.key}-${index}-url`, el)"
                :model-value="step.url || ''"
                placeholder="https://example.com or $nodeLabel.body.text"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                :dialog-key-label="
                  playwrightStepDialogKey(
                    section.label,
                    index,
                    playwrightStepActionLabel(step.action),
                    'URL',
                  )
                "
                :navigation-enabled="playwrightExpressionNavPlan.total > 1"
                :navigation-index="playwrightExprNavGlobalIndexForStep(section.key, index, 'url')"
                :navigation-total="playwrightExpressionNavPlan.total"
                @navigate="handlePlaywrightExpressionFieldNavigate"
                @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
                @update:model-value="updatePlaywrightStep(section.key, index, 'url', $event)"
              />
              <p class="text-xs text-muted-foreground">
                For textInput: <code class="font-mono">$nodeLabel.body.fieldKey</code> (e.g. $start.body.text)
              </p>
            </div>
          </template>

          <template
            v-if="['click', 'type', 'fill', 'getText', 'getAttribute', 'getHTML', 'hover', 'selectOption'].includes(step.action)"
          >
            <div class="space-y-1">
              <div class="flex items-center justify-between gap-2">
                <Label class="text-xs">Selector</Label>
                <Button
                  variant="ghost"
                  size="sm"
                  class="h-6 gap-1 text-xs"
                  @click="openSelectorPickerPlaywright(index, section.key)"
                >
                  <MousePointerClick class="h-3 w-3" />
                  Pick from page
                </Button>
              </div>
              <ExpressionInput
                :ref="(el) => bindPlaywrightExprSlotRef(`${section.key}-${index}-selector`, el)"
                :model-value="step.selector || ''"
                placeholder="button#submit or #search"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                :dialog-key-label="
                  playwrightStepDialogKey(
                    section.label,
                    index,
                    playwrightStepActionLabel(step.action),
                    'Selector',
                  )
                "
                :navigation-enabled="playwrightExpressionNavPlan.total > 1"
                :navigation-index="playwrightExprNavGlobalIndexForStep(section.key, index, 'selector')"
                :navigation-total="playwrightExpressionNavPlan.total"
                @navigate="handlePlaywrightExpressionFieldNavigate"
                @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
                @update:model-value="updatePlaywrightStep(section.key, index, 'selector', $event)"
              />
            </div>
          </template>

          <template v-if="['type', 'fill'].includes(step.action)">
            <div class="space-y-1">
              <Label class="text-xs">{{ step.action === 'type' ? 'Text' : 'Value' }}</Label>
              <ExpressionInput
                :ref="(el) => bindPlaywrightExprSlotRef(`${section.key}-${index}-typeFill`, el)"
                :model-value="step.action === 'type' ? (step.text || '') : (step.value || '')"
                :placeholder="step.action === 'type' ? 'Text to type' : 'Value to fill'"
                :rows="1"
                :nodes="workflowStore.nodes"
                :node-results="workflowStore.nodeResults"
                :edges="workflowStore.edges"
                :current-node-id="selectedNode.id"
                :dialog-node-label="selectedNodeEvaluateDialogLabel"
                :dialog-key-label="
                  playwrightStepDialogKey(
                    section.label,
                    index,
                    playwrightStepActionLabel(step.action),
                    step.action === 'type' ? 'Text' : 'Value',
                  )
                "
                :navigation-enabled="playwrightExpressionNavPlan.total > 1"
                :navigation-index="playwrightExprNavGlobalIndexForStep(section.key, index, 'typeFill')"
                :navigation-total="playwrightExpressionNavPlan.total"
                @navigate="handlePlaywrightExpressionFieldNavigate"
                @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
                @update:model-value="updatePlaywrightStep(section.key, index, step.action === 'type' ? 'text' : 'value', $event)"
              />
            </div>
          </template>

          <template v-if="step.action === 'getAttribute'">
            <div class="space-y-1">
              <Label class="text-xs">Attribute</Label>
              <Input
                :model-value="step.attribute || ''"
                placeholder="href, data-id, etc."
                @update:model-value="updatePlaywrightStep(section.key, index, 'attribute', $event as string)"
              />
            </div>
          </template>

          <template
            v-if="['getText', 'getAttribute', 'getHTML', 'getVisibleTextOnPage', 'screenshot'].includes(step.action)"
          >
            <div class="space-y-1">
              <Label class="text-xs">Output Key</Label>
              <Input
                :model-value="step.outputKey || ''"
                placeholder="e.g. pageTitle, screenshot"
                @update:model-value="updatePlaywrightStep(section.key, index, 'outputKey', $event as string)"
              />
              <p class="text-xs text-muted-foreground">
                Store result in ${{ selectedNode.data.label }}.results.key
              </p>
            </div>
          </template>

          <template v-if="step.action === 'wait'">
            <div class="space-y-1">
              <Label class="text-xs">Timeout (ms)</Label>
              <Input
                type="number"
                :model-value="step.timeout || 4000"
                placeholder="4000"
                min="0"
                @update:model-value="updatePlaywrightStep(section.key, index, 'timeout', $event ? parseInt($event as string) : 4000)"
              />
            </div>
          </template>

          <template v-if="['scrollDown', 'scrollUp'].includes(step.action)">
            <div class="space-y-1">
              <Label class="text-xs">Amount (pixels)</Label>
              <Input
                type="number"
                :model-value="step.amount ?? 300"
                placeholder="300"
                min="1"
                @update:model-value="updatePlaywrightStep(section.key, index, 'amount', $event ? parseInt($event as string) : 300)"
              />
              <p class="text-xs text-muted-foreground">
                Pixels to scroll (default 300)
              </p>
            </div>
          </template>

          <template v-if="step.action === 'aiStep'">
            <div class="space-y-2 p-2 rounded-md bg-muted/50 border border-border/50">
              <p class="text-xs text-muted-foreground">
                AI analyzes page HTML (+ optional screenshot) and returns Playwright actions. Useful for dynamic
                sites.
              </p>
              <div class="space-y-1">
                <Label class="text-xs">Instructions</Label>
                <ExpressionInput
                  :ref="(el) => bindPlaywrightExprSlotRef(`${section.key}-${index}-instructions`, el)"
                  :model-value="step.instructions || ''"
                  placeholder="e.g. Click the login button, fill email field with test@example.com"
                  :rows="3"
                  :nodes="workflowStore.nodes"
                  :node-results="workflowStore.nodeResults"
                  :edges="workflowStore.edges"
                  :current-node-id="selectedNode.id"
                  :dialog-node-label="selectedNodeEvaluateDialogLabel"
                  :dialog-key-label="
                    playwrightStepDialogKey(
                      section.label,
                      index,
                      playwrightStepActionLabel(step.action),
                      'Instructions',
                    )
                  "
                  :navigation-enabled="playwrightExpressionNavPlan.total > 1"
                  :navigation-index="playwrightExprNavGlobalIndexForStep(section.key, index, 'instructions')"
                  :navigation-total="playwrightExpressionNavPlan.total"
                  @navigate="handlePlaywrightExpressionFieldNavigate"
                  @register-field-index="onPlaywrightRegisterExpressionFieldIndex"
                  @update:model-value="updatePlaywrightStep(section.key, index, 'instructions', $event)"
                />
              </div>
              <div class="space-y-1">
                <Label class="text-xs">Credential</Label>
                <Select
                  :model-value="step.credentialId || ''"
                  :options="credentialOptions"
                  @update:model-value="(v) => { updatePlaywrightStep(section.key, index, 'credentialId', v); loadPlaywrightAiStepModels(v as string); }"
                />
              </div>
              <div class="space-y-1">
                <Label class="text-xs">Model</Label>
                <Select
                  :model-value="step.model || ''"
                  :options="playwrightAiStepModelOptions(step.credentialId, step.model)"
                  :disabled="!step.credentialId"
                  @update:model-value="updatePlaywrightStep(section.key, index, 'model', $event)"
                />
              </div>
              <div class="flex flex-col gap-2 pt-1">
                <div class="flex items-center gap-2">
                  <input
                    :id="`ai-step-log-${section.key}-${index}`"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="step.logStepsToConsole === true"
                    @change="updatePlaywrightStep(section.key, index, 'logStepsToConsole', ($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    :for="`ai-step-log-${section.key}-${index}`"
                    class="text-xs font-normal"
                  >
                    Log steps to console
                  </Label>
                </div>
                <div class="flex items-center gap-2">
                  <input
                    :id="`ai-step-save-${section.key}-${index}`"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="step.saveStepsForFuture === true"
                    @change="updatePlaywrightStep(section.key, index, 'saveStepsForFuture', ($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    :for="`ai-step-save-${section.key}-${index}`"
                    class="text-xs font-normal"
                  >
                    Save steps for future usages
                  </Label>
                </div>
                <div class="flex items-center gap-2">
                  <input
                    :id="`ai-step-screenshot-${section.key}-${index}`"
                    type="checkbox"
                    class="h-4 w-4 rounded border-input bg-background"
                    :checked="step.sendScreenshot === true"
                    @change="updatePlaywrightStep(section.key, index, 'sendScreenshot', ($event.target as HTMLInputElement).checked)"
                  >
                  <Label
                    :for="`ai-step-screenshot-${section.key}-${index}`"
                    class="text-xs font-normal"
                  >
                    Send screenshot to LLM
                  </Label>
                </div>
                <div class="flex flex-col gap-0.5">
                  <div class="flex items-center gap-2">
                    <input
                      :id="`ai-step-auto-heal-${section.key}-${index}`"
                      type="checkbox"
                      class="h-4 w-4 rounded border-input bg-background"
                      :checked="step.autoHealMode === true"
                      @change="updatePlaywrightStep(section.key, index, 'autoHealMode', ($event.target as HTMLInputElement).checked)"
                    >
                    <Label
                      :for="`ai-step-auto-heal-${section.key}-${index}`"
                      class="text-xs font-normal"
                    >
                      Auto heal mode
                    </Label>
                  </div>
                  <p class="text-xs text-muted-foreground pl-6">
                    If selector fails 2x, ask LLM for text/role-based alternative and retry
                  </p>
                </div>
              </div>
              <div class="space-y-1 pt-1">
                <Label class="text-xs">Timeout (ms) <span
                  class="text-muted-foreground font-normal"
                >(optional)</span></Label>
                <Input
                  type="number"
                  :model-value="step.aiStepTimeout ?? 30000"
                  placeholder="30000"
                  min="5000"
                  max="300000"
                  @update:model-value="updatePlaywrightStep(section.key, index, 'aiStepTimeout', parseInt(String($event), 10) || 30000)"
                />
                <p class="text-xs text-muted-foreground">
                  Timeout for LLM API call (default 30000 ms = 30 s)
                </p>
              </div>
              <div
                v-if="step.savedSteps?.length"
                class="mt-2 pt-2 border-t border-border/50 space-y-1"
              >
                <Label class="text-xs text-muted-foreground">
                  Saved steps ({{ step.savedSteps.length }}) — will be reused without LLM call
                </Label>
                <div class="space-y-1">
                  <div
                    v-for="(s, i) in step.savedSteps"
                    :key="`${section.key}-${index}-${i}`"
                    class="rounded border border-border/50 bg-background/50 overflow-hidden"
                  >
                    <div class="flex items-center gap-1 px-2 py-1.5 min-h-0">
                      <button
                        type="button"
                        class="flex-1 min-w-0 flex items-center gap-2 text-left text-xs font-mono text-muted-foreground hover:bg-muted/50 transition-colors rounded py-0.5 -mx-1 px-1"
                        @click="expandedSavedStepKey = expandedSavedStepKey === savedStepKey(section.key, index, i) ? null : savedStepKey(section.key, index, i)"
                      >
                        <span class="truncate">{{ formatSavedStep(s) }}</span>
                        <ChevronDown
                          v-if="expandedSavedStepKey === savedStepKey(section.key, index, i)"
                          class="h-3 w-3 shrink-0"
                        />
                        <ChevronRight
                          v-else
                          class="h-3 w-3 shrink-0"
                        />
                      </button>
                      <button
                        type="button"
                        class="shrink-0 flex items-center justify-center w-8 h-8 rounded-md text-red-500 hover:bg-red-500/10 transition-colors"
                        aria-label="Remove saved step"
                        @click="removePlaywrightStepSavedStep(section.key, index, i)"
                      >
                        <Trash2 class="h-4 w-4" />
                      </button>
                    </div>
                    <div
                      v-if="expandedSavedStepKey === savedStepKey(section.key, index, i)"
                      class="px-2 pb-2 pt-1 space-y-1.5 border-t border-border/50"
                    >
                      <div class="space-y-1">
                        <Label class="text-xs">Action</Label>
                        <div
                          class="font-mono text-xs h-7 px-2 py-1.5 rounded-md bg-muted/50 text-muted-foreground border border-transparent"
                        >
                          {{ s.action }}
                        </div>
                      </div>
                      <div
                        v-if="['click', 'fill', 'type', 'hover', 'selectOption'].includes(s.action)"
                        class="space-y-1"
                      >
                        <Label class="text-xs">Selector</Label>
                        <Input
                          :model-value="s.selector ?? ''"
                          placeholder="e.g. button[type=submit]"
                          class="font-mono text-xs h-7"
                          @update:model-value="updatePlaywrightStepSavedStep(section.key, index, i, 'selector', $event || undefined)"
                        />
                      </div>
                      <div
                        v-if="s.action === 'type'"
                        class="space-y-1"
                      >
                        <Label class="text-xs">Text</Label>
                        <Input
                          :model-value="s.text ?? ''"
                          placeholder="Text to type"
                          class="font-mono text-xs h-7"
                          @update:model-value="updatePlaywrightStepSavedStep(section.key, index, i, 'text', $event)"
                        />
                      </div>
                      <div
                        v-if="['fill', 'selectOption'].includes(s.action)"
                        class="space-y-1"
                      >
                        <Label class="text-xs">Value</Label>
                        <Input
                          :model-value="s.value ?? ''"
                          placeholder="Value"
                          class="font-mono text-xs h-7"
                          @update:model-value="updatePlaywrightStepSavedStep(section.key, index, i, 'value', $event)"
                        />
                      </div>
                      <div
                        v-if="s.action === 'wait'"
                        class="space-y-1"
                      >
                        <Label class="text-xs">Timeout (ms)</Label>
                        <Input
                          type="number"
                          :model-value="s.timeout ?? 2000"
                          placeholder="2000"
                          min="0"
                          class="font-mono text-xs h-7"
                          @update:model-value="updatePlaywrightStepSavedStep(section.key, index, i, 'timeout', $event ? parseInt(String($event), 10) : undefined)"
                        />
                      </div>
                      <div
                        v-if="['scrollDown', 'scrollUp'].includes(s.action)"
                        class="space-y-1"
                      >
                        <Label class="text-xs">Amount (px)</Label>
                        <Input
                          type="number"
                          :model-value="s.amount ?? 300"
                          placeholder="300"
                          min="0"
                          class="font-mono text-xs h-7"
                          @update:model-value="updatePlaywrightStepSavedStep(section.key, index, i, 'amount', $event ? parseInt(String($event), 10) : undefined)"
                        />
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </template>

          <div
            v-if="
              !['navigate', 'wait', 'scrollDown', 'scrollUp'].includes(step.action)
                && (step.selector || step.action === 'getVisibleTextOnPage')
            "
            class="space-y-1"
          >
            <Label class="text-xs">Step Timeout (ms, optional)</Label>
            <Input
              type="number"
              :model-value="step.timeout || ''"
              placeholder="30000"
              min="0"
              @update:model-value="updatePlaywrightStep(section.key, index, 'timeout', $event ? parseInt($event as string) : undefined)"
            />
          </div>
        </div>

        <p
          v-if="!getPlaywrightSteps(section.key).length"
          class="text-xs text-muted-foreground"
        >
          {{ section.emptyText }}
        </p>
      </div>
    </div>

    <div class="space-y-2 pt-2 border-t">
      <div class="flex flex-col gap-1">
        <div class="flex items-center gap-2">
          <input
            id="playwright-headless"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="selectedNode.data.playwrightHeadless !== false"
            @change="updateNodeData('playwrightHeadless', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="playwright-headless"
            class="text-sm font-normal"
          >
            Headless mode
          </Label>
        </div>
        <p class="text-xs text-muted-foreground">
          Only applies in local development. Docker always runs headless (no display).
        </p>
      </div>
      <div class="flex flex-col gap-1">
        <div class="flex items-center gap-2">
          <input
            id="playwright-capture-network"
            type="checkbox"
            class="h-4 w-4 rounded border-input bg-background"
            :checked="selectedNode.data.playwrightCaptureNetwork === true"
            @change="updateNodeData('playwrightCaptureNetwork', ($event.target as HTMLInputElement).checked)"
          >
          <Label
            for="playwright-capture-network"
            class="text-sm font-normal"
          >
            Capture network requests
          </Label>
        </div>
        <p class="text-xs text-muted-foreground">
          Capture JSON API responses, headers, and cookies during execution.
        </p>
      </div>
      <div class="space-y-1">
        <Label class="text-xs">Timeout (ms)</Label>
        <Input
          type="number"
          :model-value="selectedNode.data.playwrightTimeout || 30000"
          placeholder="30000"
          min="5000"
          max="120000"
          @update:model-value="updateNodeData('playwrightTimeout', $event ? parseInt($event as string) : 30000)"
        />
      </div>
    </div>

    <div class="space-y-2 pt-2 border-t">
      <Label class="text-muted-foreground">Output</Label>
      <div class="text-xs font-mono space-y-1 text-muted-foreground">
        <div>${{ selectedNode.data.label }}.status - "ok" on success</div>
        <div>${{ selectedNode.data.label }}.results - Output from getText/getAttribute/getHTML/getVisibleTextOnPage/screenshot</div>
        <div>${{ selectedNode.data.label }}.screenshot - Base64 screenshot if step has outputKey</div>
        <div v-if="selectedNode.data.playwrightCaptureNetwork || selectedNode.data.playwrightAuthEnabled">
          ${{ selectedNode.data.label }}.cookies - HTTP cookies
        </div>
        <template v-if="selectedNode.data.playwrightCaptureNetwork">
          <div>${{ selectedNode.data.label }}.networkRequests - Captured JSON responses (max 200)</div>
          <div>${{ selectedNode.data.label }}.localStorage - Browser localStorage key-value pairs</div>
          <div>${{ selectedNode.data.label }}.sessionStorage - Browser sessionStorage key-value pairs</div>
        </template>
      </div>
    </div>
  </template>
</template>
