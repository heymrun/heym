<script setup lang="ts">
import { computed } from "vue";
import { X } from "lucide-vue-next";

import type { CollabUserView } from "@/features/collab/useCanvasCollab";
import { collabTextColor } from "@/features/collab/colors";
import { useCollabContext } from "@/features/collab/useCanvasCollab";

const collab = useCollabContext();
const leader = computed<CollabUserView | null>(() => collab?.followedUser.value ?? null);
</script>

<template>
  <!-- Frames the whole editor, above dialogs and the AI Assistant. -->
  <div
    v-if="collab && leader"
    class="pointer-events-none fixed inset-0 z-[10000] border-2"
    :style="{ borderColor: leader.color }"
    data-testid="collab-follow-frame"
  >
    <div
      class="pointer-events-auto absolute bottom-3 left-1/2 flex -translate-x-1/2 items-center gap-2 rounded-full px-3 py-1 text-xs font-medium shadow"
      data-collab-keep-follow
      :style="{ backgroundColor: leader.color, color: collabTextColor(leader.color) }"
    >
      <span>Following {{ leader.name }} · Esc to stop</span>
      <button
        type="button"
        class="rounded-full p-0.5 hover:bg-black/20"
        aria-label="Stop following"
        @click="collab.stopFollowing()"
      >
        <X class="h-3 w-3" />
      </button>
    </div>
  </div>
</template>
