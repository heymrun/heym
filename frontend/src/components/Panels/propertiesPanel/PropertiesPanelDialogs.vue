<script setup lang="ts">
import { AlertTriangle, X, XCircle } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import SelectorPickerDialog from "@/components/Dialogs/SelectorPickerDialog.vue";
import SkillBuilderModal from "@/components/Panels/SkillBuilderModal.vue";
import SkillHistoryDialog from "@/components/Dialogs/SkillHistoryDialog.vue";
import { usePropertiesPanelContext } from "./usePropertiesPanelController";

const {
  workflowStore,
  validationErrors,
  showValidationDialog,
  selectorPickerOpen,
  selectorPickerInitialUrl,
  onSelectorPicked,
  selectedNode,
  skillBuilderOpen,
  skillBuilderTargetSkill,
  skillHistoryOpen,
  skillHistoryTarget,
  handleSkillHistoryEdit,
  handleSkillHistoryRevert,
  handleSkillHistoryFineTune,
  handleSkillHistoryExpandSkill,
  handleSkillBuilderSave,
  closeValidationDialog,
  selectNodeFromError,
  imageLightboxSrc,
} = usePropertiesPanelContext();
</script>

<template>
  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="showValidationDialog"
        class="fixed inset-0 z-50 flex items-center justify-center"
      >
        <div
          class="absolute inset-0 bg-black/50 backdrop-blur-sm"
          @click="closeValidationDialog"
        />
        <div
          class="relative bg-card border rounded-lg shadow-md w-[90vw] max-w-[400px] max-h-[80vh] overflow-hidden overflow-x-hidden"
        >
          <div class="flex items-center justify-between p-4 border-b bg-destructive/10">
            <div class="flex items-center gap-2">
              <AlertTriangle class="w-5 h-5 text-destructive" />
              <h3 class="font-semibold text-destructive">
                Configuration Required
              </h3>
            </div>
            <button
              class="p-2 rounded hover:bg-muted transition-colors min-h-[44px] min-w-[44px] flex items-center justify-center"
              @click="closeValidationDialog"
            >
              <X class="w-4 h-4" />
            </button>
          </div>
          <div class="p-4">
            <p class="text-sm text-muted-foreground mb-4">
              Please fix the following issues before running the workflow:
            </p>
            <div class="space-y-2 max-h-[300px] overflow-y-auto">
              <div
                v-for="error in validationErrors"
                :key="`${error.nodeId}-${error.message}`"
                class="flex items-start gap-3 p-3 rounded-md bg-muted/50 hover:bg-muted cursor-pointer transition-colors"
                @click="selectNodeFromError(error.nodeId)"
              >
                <XCircle class="w-4 h-4 text-destructive shrink-0 mt-0.5" />
                <div class="flex-1 min-w-0">
                  <div class="flex items-center gap-2">
                    <span class="font-medium text-sm">{{ error.nodeLabel }}</span>
                    <span class="text-xs px-1.5 py-0.5 rounded bg-muted-foreground/20 text-muted-foreground">
                      {{ error.nodeType }}
                    </span>
                  </div>
                  <p class="text-xs text-muted-foreground mt-0.5">
                    {{ error.message }}
                  </p>
                </div>
              </div>
            </div>
          </div>
          <div class="p-4 border-t bg-muted/30">
            <Button
              variant="outline"
              class="w-full"
              @click="closeValidationDialog"
            >
              Close
            </Button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>

  <Teleport to="body">
    <Transition name="fade">
      <div
        v-if="imageLightboxSrc"
        class="fixed inset-0 z-[100] flex items-center justify-center bg-black/80 backdrop-blur-sm p-4"
        @click="imageLightboxSrc = null"
      >
        <img
          :src="imageLightboxSrc"
          alt="Enlarged"
          class="max-w-[95vw] max-h-[95vh] object-contain rounded-lg shadow-2xl"
          @click.stop
        >
      </div>
    </Transition>
  </Teleport>

  <SelectorPickerDialog
    :open="selectorPickerOpen"
    :initial-url="selectorPickerInitialUrl"
    @close="selectorPickerOpen = false"
    @select="onSelectorPicked"
  />

  <SkillBuilderModal
    :open="skillBuilderOpen"
    :credential-id="selectedNode?.data?.credentialId || ''"
    :existing-skill="skillBuilderTargetSkill"
    :model="selectedNode?.data?.model || ''"
    @save="handleSkillBuilderSave"
    @update:open="skillBuilderOpen = $event"
  />

  <SkillHistoryDialog
    :open="skillHistoryOpen"
    :workflow-id="workflowStore.currentWorkflow?.id ?? ''"
    :agent-node-id="selectedNode?.id ?? ''"
    :skill="skillHistoryTarget?.skill ?? null"
    :skill-index="skillHistoryTarget?.skillIndex ?? -1"
    :ai-edit-disabled="!selectedNode?.data?.credentialId || !selectedNode?.data?.model"
    @edit-snapshot="handleSkillHistoryEdit"
    @revert-snapshot="handleSkillHistoryRevert"
    @fine-tune="handleSkillHistoryFineTune"
    @expand-skill="handleSkillHistoryExpandSkill"
    @update:open="skillHistoryOpen = $event"
  />
</template>
