<script setup lang="ts">
/** Whether cards move to the next column on their own; off for a plain task board. */
const enabled = defineModel<boolean>({ required: true });
</script>

<template>
  <label class="flex cursor-pointer items-start gap-2.5 rounded-lg border border-border/60 p-3 text-sm">
    <input
      v-model="enabled"
      type="checkbox"
      class="mt-0.5 h-4 w-4 shrink-0 accent-primary"
      data-testid="board-auto-advance"
    >
    <span class="flex flex-col gap-0.5">
      <span class="font-medium">Advance cards automatically</span>
      <span class="text-xs text-muted-foreground">
        When a column's workflows succeed, or a card enters a column without workflows, the card
        moves on to the next column. Turn it off for a plain task board where cards stay where
        people put them.
      </span>
    </span>
  </label>
</template>
