<script setup lang="ts">
import { computed } from "vue";
import { CalendarClock, Flag } from "lucide-vue-next";

import type { BoardCard, BoardMember, CardPriority } from "@/types/board";
import type { DueState } from "@/lib/boardCardFields";
import UserAvatar from "@/components/ui/UserAvatar.vue";
import { cardBadgeModel, PRIORITY_LABELS } from "@/lib/boardCardFields";

const props = defineProps<{ card: BoardCard; members: BoardMember[]; today: string }>();

const model = computed(() => cardBadgeModel(props.card, props.members, props.today));
const visible = computed<boolean>(() => {
  const m = model.value;
  return Boolean(m.assignee || m.priority || m.due || m.labels.length);
});

const PRIORITY_TONES: Record<CardPriority, string> = {
  urgent: "border-red-500/40 bg-red-500/10 text-red-500",
  high: "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400",
  medium: "border-border bg-muted/60 text-foreground/80",
  low: "border-border bg-muted/40 text-muted-foreground",
};

const DUE_TONES: Record<DueState, string> = {
  overdue: "border-red-500/40 bg-red-500/10 text-red-500",
  today: "border-amber-500/40 bg-amber-500/10 text-amber-600 dark:text-amber-400",
  soon: "border-border bg-muted/60 text-foreground/80",
  later: "border-border bg-muted/40 text-muted-foreground",
};

const DUE_TITLES: Record<DueState, string> = {
  overdue: "Overdue",
  today: "Due today",
  soon: "Due this week",
  later: "Due",
};
</script>

<template>
  <div
    v-if="visible"
    class="mt-2 flex flex-wrap items-center gap-1 text-[11px] leading-4"
    :data-testid="`board-card-badges-${card.id}`"
  >
    <span
      v-if="model.assignee"
      class="inline-flex max-w-[9rem] items-center gap-1 rounded-full border border-border bg-background/60 py-0.5 pl-0.5 pr-1.5"
      :title="`Assigned to ${model.assignee.name}`"
      :data-testid="`board-card-assignee-${card.id}`"
    >
      <UserAvatar
        :user-id="model.assignee.userId"
        :name="model.assignee.name"
        :email="model.assignee.email"
        class="h-4 w-4 bg-primary/15 text-[9px] font-semibold text-primary"
      />
      <span class="truncate">{{ model.assignee.name }}</span>
    </span>
    <span
      v-if="model.priority"
      class="inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 font-medium"
      :class="PRIORITY_TONES[model.priority]"
      :title="`Priority: ${PRIORITY_LABELS[model.priority]}`"
      :data-testid="`board-card-priority-${card.id}`"
    >
      <Flag class="h-3 w-3" />
      {{ PRIORITY_LABELS[model.priority] }}
    </span>
    <span
      v-if="model.due"
      class="inline-flex items-center gap-0.5 rounded-full border px-1.5 py-0.5 font-medium"
      :class="DUE_TONES[model.due.state]"
      :title="`${DUE_TITLES[model.due.state]}: ${model.due.date}`"
      :data-due="model.due.state"
      :data-testid="`board-card-due-${card.id}`"
    >
      <CalendarClock class="h-3 w-3" />
      {{ model.due.label }}
    </span>
    <span
      v-for="label in model.labels"
      :key="label"
      class="max-w-[7rem] truncate rounded-full bg-primary/10 px-1.5 py-0.5 text-primary dark:bg-primary/20 dark:text-brand-primary-soft"
      :data-testid="`board-card-label-${card.id}`"
      :title="label"
    >
      {{ label }}
    </span>
    <span
      v-if="model.moreLabels"
      class="rounded-full bg-muted px-1.5 py-0.5 text-muted-foreground"
      :title="card.fields.labels.join(', ')"
    >
      +{{ model.moreLabels }}
    </span>
  </div>
</template>
