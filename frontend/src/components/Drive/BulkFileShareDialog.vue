<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue";
import { Link, Users } from "lucide-vue-next";

import type { CreateShareRequest } from "@/types/file";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { filesApi } from "@/services/api";
import { onDismissOverlays, pushOverlayState } from "@/composables/useOverlayBackHandler";

const props = defineProps<{
  open: boolean;
  fileIds: string[];
}>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "updated"): void;
}>();

const error = ref("");
const result = ref<{ succeeded: number; failed: number } | null>(null);
const expiresHours = ref<string>("");
const basicAuthPassword = ref("");
const maxDownloads = ref<string>("");
const busy = ref(false);
// Snapshot ids on open: the selection in the parent clears after the first action.
const targetIds = ref<string[]>([]);

let unsubDismiss: (() => void) | null = null;

watch(
  () => props.open,
  (open) => {
    if (open) {
      targetIds.value = [...props.fileIds];
      error.value = "";
      result.value = null;
      expiresHours.value = "";
      basicAuthPassword.value = "";
      maxDownloads.value = "";
      pushOverlayState();
      unsubDismiss = onDismissOverlays(() => emit("close"));
    } else {
      unsubDismiss?.();
      unsubDismiss = null;
    }
  },
);

onUnmounted(() => {
  unsubDismiss?.();
});

async function setTeamSharing(enabled: boolean): Promise<void> {
  busy.value = true;
  error.value = "";
  result.value = null;
  try {
    const res = await filesApi.bulkSetTeamSharing(targetIds.value, enabled);
    result.value = { succeeded: res.succeeded.length, failed: res.failed.length };
    emit("updated");
  } catch {
    error.value = "Failed to update team sharing";
  } finally {
    busy.value = false;
  }
}

async function createShareLinks(): Promise<void> {
  busy.value = true;
  error.value = "";
  result.value = null;
  try {
    const data: CreateShareRequest = {};
    if (expiresHours.value) data.expires_hours = parseInt(expiresHours.value);
    if (basicAuthPassword.value) data.basic_auth_password = basicAuthPassword.value;
    if (maxDownloads.value) data.max_downloads = parseInt(maxDownloads.value);

    const res = await filesApi.bulkCreateShare(targetIds.value, data);
    result.value = { succeeded: res.succeeded.length, failed: res.failed.length };
    expiresHours.value = "";
    basicAuthPassword.value = "";
    maxDownloads.value = "";
    emit("updated");
  } catch {
    error.value = "Failed to create share links";
  } finally {
    busy.value = false;
  }
}
</script>

<template>
  <Dialog
    :open="open"
    :title="`Bulk actions · ${targetIds.length} file${targetIds.length === 1 ? '' : 's'}`"
    @close="emit('close')"
  >
    <div class="space-y-4">
      <!-- Team sharing -->
      <div class="space-y-2 p-3 rounded-lg border border-border bg-muted/30">
        <p class="text-sm font-medium flex items-center gap-2">
          <Users class="w-3.5 h-3.5" />
          Team sharing
        </p>
        <p class="text-xs text-muted-foreground">
          Members of your current teams can view and download these files, but cannot manage them.
        </p>
        <div class="flex flex-wrap gap-2 pt-1">
          <Button
            size="sm"
            :disabled="busy"
            @click="setTeamSharing(true)"
          >
            Share all with my teams
          </Button>
          <Button
            size="sm"
            variant="outline"
            :disabled="busy"
            @click="setTeamSharing(false)"
          >
            Remove team sharing
          </Button>
        </div>
      </div>

      <!-- Create share links -->
      <div class="space-y-3 p-3 rounded-lg border border-border bg-muted/30">
        <p class="text-sm font-medium">
          Create share link for each file
        </p>
        <div class="grid grid-cols-3 gap-2">
          <div>
            <Label class="text-xs">Expires (hours)</Label>
            <Input
              v-model="expiresHours"
              type="number"
              placeholder="No expiry"
              class="text-xs"
            />
          </div>
          <div>
            <Label class="text-xs">Password</Label>
            <Input
              v-model="basicAuthPassword"
              type="password"
              placeholder="No password"
              class="text-xs"
            />
          </div>
          <div>
            <Label class="text-xs">Max downloads</Label>
            <Input
              v-model="maxDownloads"
              type="number"
              placeholder="Unlimited"
              class="text-xs"
            />
          </div>
        </div>
        <Button
          size="sm"
          :disabled="busy"
          @click="createShareLinks"
        >
          <Link class="w-3.5 h-3.5 mr-1" />
          {{ busy ? "Applying..." : "Create links" }}
        </Button>
      </div>

      <!-- Result -->
      <p
        v-if="result"
        class="text-xs"
        :class="result.failed > 0 ? 'text-amber-500' : 'text-green-500'"
      >
        Applied to {{ result.succeeded }} of {{ result.succeeded + result.failed }} files.
        <span v-if="result.failed > 0">{{ result.failed }} skipped (not owned by you).</span>
      </p>

      <p
        v-if="error"
        class="text-xs text-destructive"
      >
        {{ error }}
      </p>
    </div>
  </Dialog>
</template>
