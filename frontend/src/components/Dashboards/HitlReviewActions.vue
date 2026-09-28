<script setup lang="ts">
import { Loader2 } from "lucide-vue-next";

defineProps<{
  editing: boolean;
  submitting: boolean;
  preview: boolean;
}>();

const emit = defineEmits<{
  (e: "cancel"): void;
  (e: "save"): void;
  (e: "edit"): void;
  (e: "accept"): void;
  (e: "refuse"): void;
}>();

const actionClass =
  "inline-flex h-8 shrink-0 items-center justify-center rounded-full px-3.5 text-xs font-medium leading-none whitespace-nowrap disabled:pointer-events-none disabled:opacity-50";
</script>

<template>
  <div class="mt-2 flex w-full min-w-0 shrink-0 flex-nowrap items-center gap-2 bg-card">
    <template v-if="editing">
      <button
        type="button"
        :class="[actionClass, 'border border-border bg-background text-foreground hover:bg-accent']"
        :disabled="submitting || preview"
        @click="emit('cancel')"
      >
        Cancel
      </button>
      <button
        type="button"
        :class="[actionClass, 'bg-primary text-primary-foreground hover:bg-primary/90']"
        :disabled="submitting || preview"
        @click="emit('save')"
      >
        <Loader2
          v-if="submitting"
          class="mr-1 h-3 w-3 animate-spin"
        />
        Save
      </button>
    </template>
    <template v-else>
      <button
        type="button"
        :class="[actionClass, 'bg-primary text-primary-foreground hover:bg-primary/90']"
        :disabled="submitting || preview"
        @click="emit('accept')"
      >
        <Loader2
          v-if="submitting"
          class="mr-1 h-3 w-3 animate-spin"
        />
        Approve
      </button>
      <button
        type="button"
        :class="[actionClass, 'border border-border bg-background text-foreground hover:bg-accent']"
        :disabled="submitting || preview"
        @click="emit('edit')"
      >
        Request changes
      </button>
      <button
        type="button"
        :class="[actionClass, 'bg-destructive/10 text-destructive hover:bg-destructive/15']"
        :disabled="submitting || preview"
        @click="emit('refuse')"
      >
        Reject
      </button>
    </template>
  </div>
</template>
