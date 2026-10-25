<script setup lang="ts">
import { computed } from "vue";
import { Mic, MicOff, Volume2 } from "lucide-vue-next";

import type { CollabUserView } from "@/features/collab/useCanvasCollab";
import UserAvatar from "@/components/ui/UserAvatar.vue";
import { useCollabContext } from "@/features/collab/useCanvasCollab";

const MAX_VISIBLE = 5;

const collab = useCollabContext();
const users = computed<CollabUserView[]>(() => collab?.users.value ?? []);
const visible = computed<CollabUserView[]>(() => users.value.slice(0, MAX_VISIBLE));
const hiddenCount = computed<number>(() => Math.max(0, users.value.length - MAX_VISIBLE));
const micLabel = computed<string>(() => {
  if (collab?.micError.value) return collab.micError.value;
  return collab?.micOn.value ? "Turn microphone off" : "Turn microphone on";
});
const micClass = computed<string>(() => {
  if (collab?.micOn.value) return "border-primary bg-primary/15 text-primary";
  if (collab?.micError.value) return "border-destructive bg-card text-destructive";
  return "border-border bg-card text-muted-foreground hover:text-foreground";
});

function avatarLabel(user: CollabUserView): string {
  const role = user.permission === "write" ? "can edit" : "can view";
  if (user.isSelf) return `${user.name} (you) · ${role}`;
  const action = user.following ? "click to stop following" : "click to follow";
  return `${user.name} · ${role} · ${action}`;
}

function ringStyle(user: CollabUserView): Record<string, string> {
  const width = user.following ? 5 : 4;
  return { boxShadow: `0 0 0 2px hsl(var(--background)), 0 0 0 ${width}px ${user.color}` };
}
</script>

<template>
  <div
    v-if="collab && collab.me.value"
    class="absolute left-3 top-3 z-20 hidden items-center gap-2 md:flex"
    data-testid="collab-overlay"
    data-collab-keep-follow
  >
    <div class="flex items-center -space-x-1">
      <button
        v-for="user in visible"
        :key="user.userId"
        type="button"
        class="relative flex h-7 w-7 shrink-0 items-center justify-center rounded-full"
        :class="user.isSelf ? 'cursor-default' : 'cursor-pointer'"
        :style="ringStyle(user)"
        :title="avatarLabel(user)"
        :aria-label="avatarLabel(user)"
        @click="collab.toggleFollow(user.userId)"
      >
        <UserAvatar
          :user-id="user.userId"
          :name="user.name"
          class="h-7 w-7 bg-muted text-xs font-semibold text-foreground"
          :class="user.speaking ? 'animate-pulse' : ''"
        />
        <span
          v-if="user.mic"
          class="absolute -bottom-0.5 -right-0.5 flex h-3.5 w-3.5 items-center justify-center rounded-full bg-background"
        >
          <Mic
            class="h-2.5 w-2.5"
            :style="{ color: user.color }"
          />
        </span>
        <span
          v-if="user.audioFailed"
          class="absolute -right-0.5 -top-0.5 h-2.5 w-2.5 rounded-full bg-destructive"
          title="No audio connection"
        />
      </button>
      <span
        v-if="hiddenCount > 0"
        class="flex h-7 w-7 items-center justify-center rounded-full bg-muted text-[11px] font-medium text-muted-foreground ring-2 ring-background"
      >+{{ hiddenCount }}</span>
    </div>
    <button
      type="button"
      class="flex h-7 w-7 items-center justify-center rounded-full border transition-colors"
      :class="micClass"
      :title="micLabel"
      :aria-label="micLabel"
      :aria-pressed="collab.micOn.value"
      data-testid="collab-mic-toggle"
      @click="collab.toggleMic()"
    >
      <Mic
        v-if="collab.micOn.value"
        class="h-3.5 w-3.5"
      />
      <MicOff
        v-else
        class="h-3.5 w-3.5"
      />
    </button>
    <button
      v-if="collab.autoplayBlocked.value"
      type="button"
      class="flex h-7 items-center gap-1 rounded-full border border-border bg-card px-2.5 text-xs"
      @click="collab.resumeAudio()"
    >
      <Volume2 class="h-3.5 w-3.5" />
      Enable audio
    </button>
    <span
      v-if="collab.status.value !== 'open'"
      class="text-xs text-muted-foreground"
    >Reconnecting…</span>
  </div>
</template>
