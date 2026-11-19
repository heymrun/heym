<script setup lang="ts">
import UserAvatar from "@/components/ui/UserAvatar.vue";

interface Props {
  userId?: string | null;
  name?: string | null;
  size?: "sm" | "md";
}

withDefaults(defineProps<Props>(), { userId: null, name: null, size: "sm" });
</script>

<template>
  <span
    v-if="name"
    class="inline-flex max-w-full min-w-0 items-center rounded-full border border-border bg-background/60 font-medium text-foreground/80"
    :class="size === 'md' ? 'gap-1 py-0.5 pl-0.5 pr-1.5 text-[10px]' : 'gap-0.5 py-px pl-px pr-1 text-[9px]'"
    :title="`Started by ${name}`"
    data-testid="run-history-started-by"
  >
    <UserAvatar
      :user-id="userId"
      :name="name"
      class="bg-primary/15 font-semibold text-primary dark:text-violet-300"
      :class="size === 'md' ? 'h-4 w-4 text-[9px]' : 'h-3.5 w-3.5 text-[8px]'"
    />
    <span class="truncate">{{ name }}</span>
  </span>
</template>
