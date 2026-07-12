<script setup lang="ts">
import { ref, watch } from "vue";
import { Bot, Loader2, Play, User as UserIcon } from "lucide-vue-next";

import Dialog from "@/components/ui/Dialog.vue";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import type { CardDetail } from "@/types/board";
import { boardApi } from "@/services/api";
import { useBoardStore } from "@/stores/board";

const props = defineProps<{ open: boolean; cardId: string | null }>();
const emit = defineEmits<{ (e: "close"): void }>();

const boardStore = useBoardStore();
const detail = ref<CardDetail | null>(null);
const loading = ref(false);
const comment = ref("");
const editedContent = ref("");
const savingContent = ref(false);

watch(
  () => [props.open, props.cardId] as const,
  async ([open, cardId]) => {
    if (!open || !cardId || !boardStore.activeBoard) return;
    loading.value = true;
    try {
      detail.value = await boardApi.getCard(boardStore.activeBoard.id, cardId);
      editedContent.value = detail.value.card.content;
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);

async function reload(): Promise<void> {
  if (!props.cardId || !boardStore.activeBoard) return;
  detail.value = await boardApi.getCard(boardStore.activeBoard.id, props.cardId);
}

async function saveContent(): Promise<void> {
  if (!detail.value || !boardStore.activeBoard || savingContent.value) return;
  savingContent.value = true;
  try {
    await boardApi.updateCard(boardStore.activeBoard.id, detail.value.card.id, {
      content: editedContent.value,
    });
    await reload();
  } finally {
    savingContent.value = false;
  }
}

async function submitComment(): Promise<void> {
  const content = comment.value.trim();
  if (!content || !detail.value || !boardStore.activeBoard) return;
  comment.value = "";
  await boardApi.addComment(boardStore.activeBoard.id, detail.value.card.id, content);
  await reload();
}

async function runFollowUp(): Promise<void> {
  if (!detail.value) return;
  await boardStore.runFollowUp(detail.value.card.id);
  await reload();
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString();
}
</script>

<template>
  <Dialog
    :open="open"
    :title="detail?.card.title ?? 'Card'"
    @close="emit('close')"
  >
    <div
      v-if="loading"
      class="flex items-center justify-center p-8"
    >
      <Loader2 class="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
    <div
      v-else-if="detail"
      class="flex max-h-[70vh] flex-col gap-4 overflow-y-auto p-1 text-sm"
    >
      <div class="flex items-center gap-2">
        <span
          class="rounded-full px-2 py-0.5 text-xs font-medium"
          :class="{
            'bg-emerald-500/15 text-emerald-500': detail.card.run_status === 'success',
            'bg-red-500/15 text-red-500': detail.card.run_status === 'failed',
            'bg-amber-500/15 text-amber-500':
              detail.card.run_status === 'running' || detail.card.run_status === 'pending',
            'bg-muted text-muted-foreground': detail.card.run_status === 'idle',
          }"
        >
          {{ detail.card.run_status }}
        </span>
        <Button
          size="sm"
          variant="outline"
          data-testid="card-run-followup"
          :disabled="detail.card.run_status === 'running' || detail.card.run_status === 'pending'"
          @click="runFollowUp"
        >
          <Play class="mr-1 h-3.5 w-3.5" /> Run follow-up round
        </Button>
      </div>

      <section>
        <h3 class="mb-1 text-xs font-semibold uppercase text-muted-foreground">
          Description
        </h3>
        <Textarea
          v-model="editedContent"
          :rows="4"
          placeholder="Describe the job for this card"
        />
        <div class="mt-1 flex justify-end">
          <Button
            size="sm"
            variant="ghost"
            :disabled="savingContent"
            @click="saveContent"
          >
            Save description
          </Button>
        </div>
      </section>

      <section>
        <h3 class="mb-1 text-xs font-semibold uppercase text-muted-foreground">
          Activity
        </h3>
        <div class="flex flex-col gap-2">
          <div
            v-for="activity in detail.activities"
            :key="activity.id"
            class="rounded-lg border border-border/50 p-2"
            :class="activity.kind === 'output' ? 'bg-primary/5' : ''"
          >
            <div class="mb-1 flex items-center gap-1.5 text-xs text-muted-foreground">
              <UserIcon
                v-if="activity.author_type === 'user'"
                class="h-3.5 w-3.5"
              />
              <Bot
                v-else-if="activity.author_type === 'agent'"
                class="h-3.5 w-3.5"
              />
              <span class="capitalize">{{ activity.kind }}</span>
              <span>· {{ formatTime(activity.created_at) }}</span>
            </div>
            <p class="whitespace-pre-wrap">
              {{ activity.content }}
            </p>
          </div>
          <p
            v-if="!detail.activities.length"
            class="text-xs text-muted-foreground"
          >
            No activity yet.
          </p>
        </div>
        <div class="mt-2 flex gap-2">
          <Textarea
            v-model="comment"
            :rows="2"
            placeholder="Add a comment (included in the next run's context)"
            data-testid="card-comment-input"
            @keydown.meta.enter="submitComment"
          />
          <Button
            size="sm"
            data-testid="card-comment-submit"
            :disabled="!comment.trim()"
            @click="submitComment"
          >
            Comment
          </Button>
        </div>
      </section>

      <section>
        <h3 class="mb-1 text-xs font-semibold uppercase text-muted-foreground">
          Runs
        </h3>
        <div class="flex flex-col gap-2">
          <div
            v-for="run in detail.runs"
            :key="run.id"
            class="rounded-lg border border-border/50 p-2"
          >
            <div class="flex items-center gap-2 text-xs">
              <span class="font-medium">{{ run.workflow_name }}</span>
              <span class="text-muted-foreground">
                step {{ run.chain_position + 1 }}/{{ run.chain_length }}
              </span>
              <span
                class="ml-auto rounded-full px-2 py-0.5 font-medium"
                :class="{
                  'bg-emerald-500/15 text-emerald-500': run.status === 'success',
                  'bg-red-500/15 text-red-500': run.status === 'failed',
                  'bg-amber-500/15 text-amber-500':
                    run.status === 'running' || run.status === 'pending',
                  'bg-muted text-muted-foreground':
                    run.status === 'skipped' || run.status === 'cancelled',
                }"
              >
                {{ run.status }}
              </span>
            </div>
            <p
              v-if="run.error"
              class="mt-1 text-xs text-red-500"
            >
              {{ run.error }}
            </p>
            <pre
              v-if="Object.keys(run.output).length"
              class="mt-1 max-h-40 overflow-auto rounded bg-muted/50 p-2 text-xs"
            >{{ JSON.stringify(run.output, null, 2) }}</pre>
          </div>
          <p
            v-if="!detail.runs.length"
            class="text-xs text-muted-foreground"
          >
            No runs yet. Move the card into a column with workflows to start one.
          </p>
        </div>
      </section>
    </div>
  </Dialog>
</template>
