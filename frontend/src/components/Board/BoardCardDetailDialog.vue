<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";
import {
  Bot,
  Check,
  Copy,
  Loader2,
  Paperclip,
  Play,
  Trash2,
  User as UserIcon,
} from "lucide-vue-next";

import Dialog from "@/components/ui/Dialog.vue";
import Button from "@/components/ui/Button.vue";
import Textarea from "@/components/ui/Textarea.vue";
import type { CardActivity, CardAttachment, CardDetail, CardRun } from "@/types/board";
import { boardApi } from "@/services/api";
import { useBoardStore } from "@/stores/board";
import { playSuccessSound } from "@/utils/audio";

const props = defineProps<{ open: boolean; cardId: string | null }>();
const emit = defineEmits<{ (e: "close"): void }>();

const boardStore = useBoardStore();
const detail = ref<CardDetail | null>(null);
const loading = ref(false);
const comment = ref("");
const editedContent = ref("");
const savingContent = ref(false);
const activityScroll = ref<HTMLElement | null>(null);
const activityAtBottom = ref(false);
const fileInput = ref<HTMLInputElement | null>(null);
const uploading = ref(false);
const dragActive = ref(false);

// Attachments live on the card metadata, which is what the workflows receive.
const attachments = computed<CardAttachment[]>(() => {
  const raw = detail.value?.card.card_metadata?.attachments;
  return Array.isArray(raw) ? (raw as CardAttachment[]) : [];
});

async function uploadFiles(files: File[]): Promise<void> {
  if (!files.length || !detail.value || !boardStore.activeBoard) return;
  uploading.value = true;
  try {
    for (const file of files) {
      await boardApi.addAttachment(boardStore.activeBoard.id, detail.value.card.id, file);
    }
    await reload();
    await boardStore.refreshActiveBoard();
  } finally {
    uploading.value = false;
  }
}

async function uploadAttachment(event: Event): Promise<void> {
  const input = event.target as HTMLInputElement;
  await uploadFiles(Array.from(input.files ?? []));
  input.value = "";
}

function onDragOver(): void {
  dragActive.value = true;
}

function onDragLeave(): void {
  dragActive.value = false;
}

async function onDrop(event: DragEvent): Promise<void> {
  dragActive.value = false;
  await uploadFiles(Array.from(event.dataTransfer?.files ?? []));
}

async function removeAttachment(fileId: string): Promise<void> {
  if (!detail.value || !boardStore.activeBoard) return;
  await boardApi.removeAttachment(boardStore.activeBoard.id, detail.value.card.id, fileId);
  await reload();
  await boardStore.refreshActiveBoard();
}

// Activity is stored oldest-first; the dialog always shows newest at the top.
const activitiesNewestFirst = computed(() =>
  detail.value ? [...detail.value.activities].slice().reverse() : [],
);

function onActivityScroll(): void {
  const el = activityScroll.value;
  if (!el) return;
  activityAtBottom.value = el.scrollTop + el.clientHeight >= el.scrollHeight - 2;
}

// While the dialog is open, the chime rings whenever a run finishes: the card leaves
// "running" for whatever comes next (success, failed, pending or the next column's run).
const lastStatus = ref<string | null>(null);

function announceStatus(next: CardDetail): void {
  const status = next.card.run_status;
  if (lastStatus.value === "running" && status !== "running") {
    playSuccessSound();
  }
  lastStatus.value = status;
}

let pollTimer: ReturnType<typeof setInterval> | null = null;

function stopPolling(): void {
  if (pollTimer !== null) {
    clearInterval(pollTimer);
    pollTimer = null;
  }
}

// While the card has an active run, poll its detail so the status and run
// results update live without reopening the dialog.
function syncPolling(): void {
  const status = detail.value?.card.run_status;
  const active = props.open && (status === "running" || status === "pending");
  if (active && pollTimer === null) {
    pollTimer = setInterval(() => {
      void reload();
    }, 2500);
  } else if (!active) {
    stopPolling();
  }
}

watch(
  () => [props.open, props.cardId] as const,
  async ([open, cardId]) => {
    if (!open || !cardId || !boardStore.activeBoard) {
      stopPolling();
      lastStatus.value = null;
      return;
    }
    loading.value = true;
    activityAtBottom.value = false;
    try {
      const next = await boardApi.getCard(boardStore.activeBoard.id, cardId);
      detail.value = next;
      editedContent.value = next.card.content;
      lastStatus.value = next.card.run_status;
      syncPolling();
    } finally {
      loading.value = false;
    }
  },
  { immediate: true },
);

async function reload(): Promise<void> {
  if (!props.cardId || !boardStore.activeBoard) return;
  const next = await boardApi.getCard(boardStore.activeBoard.id, props.cardId);
  detail.value = next;
  announceStatus(next);
  syncPolling();
}

onUnmounted(stopPolling);

const descriptionDirty = computed<boolean>(
  () => detail.value !== null && editedContent.value !== detail.value.card.content,
);
const descriptionSaved = ref(false);

async function saveContent(): Promise<void> {
  if (!detail.value || !boardStore.activeBoard || savingContent.value) return;
  savingContent.value = true;
  try {
    await boardApi.updateCard(boardStore.activeBoard.id, detail.value.card.id, {
      content: editedContent.value,
    });
    await reload();
    // The board card shows the description snippet, so refresh it too.
    await boardStore.refreshActiveBoard();
    descriptionSaved.value = true;
    setTimeout(() => {
      descriptionSaved.value = false;
    }, 2500);
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
  // The answer releases the planning gate, so the card starts running in the next
  // column — refresh the board so the canvas card turns active right away.
  await boardStore.refreshActiveBoard();
}

async function runFollowUp(): Promise<void> {
  if (!detail.value) return;
  await boardStore.runFollowUp(detail.value.card.id);
  await reload();
}

function formatTime(iso: string): string {
  return new Date(iso).toLocaleString();
}

// Activity text (workflow output is humanized to markdown by the board mapper).
function renderMarkdown(raw: string): string {
  const html = marked(raw ?? "", { breaks: true, gfm: true }) as string;
  return DOMPurify.sanitize(html, { ADD_ATTR: ["target", "rel"] });
}

const copiedActivityId = ref<string | null>(null);

async function copyActivity(activity: CardActivity): Promise<void> {
  try {
    await navigator.clipboard.writeText(activity.content);
    copiedActivityId.value = activity.id;
    setTimeout(() => {
      if (copiedActivityId.value === activity.id) copiedActivityId.value = null;
    }, 1500);
  } catch {
    // clipboard unavailable; ignore
  }
}

async function removeActivity(activityId: string): Promise<void> {
  if (!detail.value || !boardStore.activeBoard) return;
  await boardApi.removeActivity(boardStore.activeBoard.id, detail.value.card.id, activityId);
  await reload();
}

const copiedRunId = ref<string | null>(null);

async function copyRun(run: CardRun): Promise<void> {
  const text = Object.keys(run.output).length
    ? JSON.stringify(run.output, null, 2)
    : (run.error ?? "");
  try {
    await navigator.clipboard.writeText(text);
    copiedRunId.value = run.id;
    setTimeout(() => {
      if (copiedRunId.value === run.id) copiedRunId.value = null;
    }, 1500);
  } catch {
    // clipboard unavailable; ignore
  }
}
</script>

<template>
  <Dialog
    :open="open"
    :title="detail?.card.title ?? 'Card'"
    @close="emit('close')"
  >
    <template
      v-if="detail"
      #subtitle
    >
      <span
        class="inline-block rounded-full px-2 py-0.5 text-xs font-medium"
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
    </template>
    <template #header-trailing>
      <Button
        v-if="detail"
        size="icon"
        variant="outline"
        data-testid="card-run-followup"
        title="Run follow-up round"
        aria-label="Run follow-up round"
        :disabled="detail.card.run_status === 'running' || detail.card.run_status === 'pending'"
        @click="runFollowUp"
      >
        <Play class="h-4 w-4" />
      </Button>
    </template>
    <div
      v-if="loading"
      class="flex items-center justify-center p-8"
    >
      <Loader2 class="h-5 w-5 animate-spin text-muted-foreground" />
    </div>
    <div
      v-else-if="detail"
      class="flex flex-col gap-3 p-1 text-sm"
    >
      <section>
        <h3 class="mb-1 text-xs font-semibold uppercase text-muted-foreground">
          Description
        </h3>
        <Textarea
          v-model="editedContent"
          :rows="3"
          placeholder="Describe the job for this card"
        />
        <div class="mt-2 flex items-center justify-end gap-2">
          <span
            v-if="descriptionSaved"
            class="inline-flex items-center gap-1 text-xs text-emerald-500"
            data-testid="card-description-saved"
          >
            <Check class="h-3.5 w-3.5" /> Description saved
          </span>
          <Button
            v-if="descriptionDirty || savingContent"
            size="sm"
            data-testid="card-description-save"
            :disabled="savingContent"
            @click="saveContent"
          >
            Save description
          </Button>
        </div>
      </section>

      <section>
        <h3 class="mb-1 text-xs font-semibold uppercase text-muted-foreground">
          Attachments
        </h3>
        <div class="flex flex-col gap-1.5">
          <div
            v-for="attachment in attachments"
            :key="attachment.file_id"
            class="flex items-center gap-2 rounded-md border border-border/60 px-2 py-1.5 text-sm"
            :data-testid="`card-attachment-${attachment.name}`"
          >
            <Paperclip class="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
            <a
              :href="attachment.url"
              target="_blank"
              rel="noopener"
              class="min-w-0 flex-1 truncate hover:underline"
            >
              {{ attachment.name }}
            </a>
            <button
              class="rounded p-1 hover:bg-destructive/10"
              :aria-label="`Remove ${attachment.name}`"
              @click="removeAttachment(attachment.file_id)"
            >
              <Trash2 class="h-3.5 w-3.5 text-destructive" />
            </button>
          </div>
          <!-- Files can be dropped anywhere on this box, or picked with the button. -->
          <div
            class="flex items-center gap-3 rounded-lg border border-dashed px-3 py-2.5 text-xs transition-colors"
            :class="
              dragActive
                ? 'border-primary bg-primary/5 text-foreground'
                : 'border-border/70 text-muted-foreground'
            "
            data-testid="card-attachment-dropzone"
            @dragover.prevent="onDragOver"
            @dragenter.prevent="onDragOver"
            @dragleave="onDragLeave"
            @drop.prevent="onDrop"
          >
            <input
              ref="fileInput"
              type="file"
              multiple
              class="hidden"
              data-testid="card-attachment-input"
              @change="uploadAttachment"
            >
            <Button
              size="sm"
              variant="outline"
              class="shrink-0"
              :disabled="uploading"
              data-testid="card-attachment-add"
              @click="fileInput?.click()"
            >
              <Loader2
                v-if="uploading"
                class="mr-1 h-3.5 w-3.5 animate-spin"
              />
              <Paperclip
                v-else
                class="mr-1 h-3.5 w-3.5"
              />
              Attach file
            </Button>
            <span>{{ dragActive ? "Drop to attach" : "or drop files here" }}</span>
          </div>
        </div>
      </section>

      <section>
        <h3 class="mb-1 text-xs font-semibold uppercase text-muted-foreground">
          Activity
        </h3>
        <div class="relative">
          <div
            ref="activityScroll"
            class="flex max-h-[286px] flex-col gap-2 overflow-y-auto pr-1"
            @scroll="onActivityScroll"
          >
            <div
              v-for="activity in activitiesNewestFirst"
              :key="activity.id"
              class="group rounded-lg border border-border/50 p-2"
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
                <div class="ml-auto flex items-center gap-1 opacity-0 transition-opacity group-hover:opacity-100">
                  <button
                    class="rounded p-1 hover:text-foreground"
                    :data-testid="`activity-copy-${activity.id}`"
                    :aria-label="copiedActivityId === activity.id ? 'Copied' : 'Copy text'"
                    @click="copyActivity(activity)"
                  >
                    <Check
                      v-if="copiedActivityId === activity.id"
                      class="h-3.5 w-3.5 text-emerald-500"
                    />
                    <Copy
                      v-else
                      class="h-3.5 w-3.5"
                    />
                  </button>
                  <button
                    class="rounded p-1 hover:bg-destructive/10"
                    :data-testid="`activity-delete-${activity.id}`"
                    aria-label="Delete activity"
                    @click="removeActivity(activity.id)"
                  >
                    <Trash2 class="h-3.5 w-3.5 text-destructive" />
                  </button>
                </div>
              </div>
              <!-- eslint-disable vue/no-v-html -- sanitized with DOMPurify -->
              <div
                class="board-activity-md text-sm"
                v-html="renderMarkdown(activity.content)"
              />
            </div>
            <p
              v-if="!detail.activities.length"
              class="text-xs text-muted-foreground"
            >
              No activity yet.
            </p>
          </div>
          <div
            v-if="detail.activities.length > 5 && !activityAtBottom"
            class="pointer-events-none absolute inset-x-0 bottom-0 h-10 rounded-b-lg bg-gradient-to-t from-card to-transparent"
          />
        </div>
        <div class="mt-2 flex flex-col gap-2">
          <Textarea
            v-model="comment"
            :rows="2"
            placeholder="Add a comment (included in the next run's context)"
            data-testid="card-comment-input"
            @keydown.meta.enter="submitComment"
          />
          <div class="flex justify-end">
            <Button
              size="sm"
              data-testid="card-comment-submit"
              :disabled="!comment.trim()"
              @click="submitComment"
            >
              Comment
            </Button>
          </div>
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
            class="group rounded-lg border border-border/50 p-2"
          >
            <div class="flex items-center gap-2 text-xs">
              <span class="font-medium">{{ run.workflow_name }}</span>
              <span class="text-muted-foreground">
                step {{ run.chain_position + 1 }}/{{ run.chain_length }}
              </span>
              <div class="ml-auto flex items-center gap-1.5">
                <button
                  class="hidden items-center gap-1 rounded px-1.5 py-0.5 text-muted-foreground hover:text-foreground group-hover:inline-flex"
                  :data-testid="`run-copy-${run.id}`"
                  @click.stop="copyRun(run)"
                >
                  <Check
                    v-if="copiedRunId === run.id"
                    class="h-3 w-3 text-emerald-500"
                  />
                  <Copy
                    v-else
                    class="h-3 w-3"
                  />
                  {{ copiedRunId === run.id ? "Copied" : "Copy" }}
                </button>
                <span
                  class="rounded-full px-2 py-0.5 font-medium"
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
            </div>
            <p class="mt-1 text-[11px] text-muted-foreground">
              {{ formatTime(run.started_at) }}
              <template v-if="run.finished_at">
                · {{ formatTime(run.finished_at) }}
              </template>
            </p>
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

<style scoped>
.board-activity-md :deep(p) {
  margin: 0 0 0.4rem;
  white-space: pre-wrap;
}

.board-activity-md :deep(p:last-child) {
  margin-bottom: 0;
}

.board-activity-md :deep(h1),
.board-activity-md :deep(h2),
.board-activity-md :deep(h3) {
  margin: 0.4rem 0 0.25rem;
  font-size: 0.875rem;
  font-weight: 600;
}

.board-activity-md :deep(ul),
.board-activity-md :deep(ol) {
  margin: 0 0 0.4rem;
  padding-left: 1.35rem;
}

.board-activity-md :deep(ul) {
  list-style: disc;
}

.board-activity-md :deep(ol) {
  list-style: decimal;
}

.board-activity-md :deep(li) {
  margin: 0.1rem 0;
}

.board-activity-md :deep(li::marker) {
  color: hsl(var(--foreground));
  font-weight: 700;
}

.board-activity-md :deep(strong) {
  font-weight: 600;
}

.board-activity-md :deep(a) {
  color: hsl(var(--primary));
  text-decoration: underline;
}

.board-activity-md :deep(code) {
  border-radius: 0.25rem;
  background: hsl(var(--muted));
  padding: 0.05rem 0.25rem;
  font-size: 0.78rem;
}

.board-activity-md :deep(pre) {
  overflow-x: auto;
  border-radius: 0.375rem;
  background: hsl(var(--muted));
  padding: 0.5rem;
}

.board-activity-md :deep(pre code) {
  background: transparent;
  padding: 0;
}
</style>
