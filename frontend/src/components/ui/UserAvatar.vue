<script setup lang="ts">
import { computed } from "vue";

import { getAvatarLoadState, setAvatarLoadState, userInitial } from "@/lib/userAvatar";
import { avatarApi } from "@/services/api";

interface Props {
  userId?: string | null;
  name?: string | null;
  email?: string | null;
}

const props = defineProps<Props>();

const loadState = computed(() => (props.userId ? getAvatarLoadState(props.userId) : "missing"));
const src = computed((): string | null =>
  props.userId && loadState.value !== "missing" ? avatarApi.url(props.userId) : null,
);
const initial = computed((): string => userInitial(props.name, props.email));

function markLoaded(): void {
  if (props.userId) setAvatarLoadState(props.userId, "loaded");
}

function markMissing(): void {
  if (props.userId) setAvatarLoadState(props.userId, "missing");
}
</script>

<template>
  <!-- Size and fallback colours come from the caller's class. The initial (or the default
       slot) stays underneath until the Gravatar picture has loaded, so nothing flickers. -->
  <span
    class="relative inline-flex shrink-0 select-none items-center justify-center overflow-hidden rounded-full"
    aria-hidden="true"
  >
    <slot v-if="loadState !== 'loaded'">{{ initial }}</slot>
    <img
      v-if="src"
      :src="src"
      alt=""
      draggable="false"
      decoding="async"
      class="absolute inset-0 h-full w-full object-cover transition-opacity duration-200"
      :class="loadState === 'loaded' ? 'opacity-100' : 'opacity-0'"
      @load="markLoaded"
      @error="markMissing"
    >
  </span>
</template>
