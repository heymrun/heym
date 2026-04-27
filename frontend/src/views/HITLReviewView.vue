<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { useRoute } from "vue-router";
import { CheckCircle2, Clock3, Loader2, RefreshCcw, ShieldAlert, XCircle } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { hitlApi } from "@/services/api";
import type { HITLReview } from "@/types/workflow";

const route = useRoute();
const token = computed(() => String(route.params.token || ""));

const review = ref<HITLReview | null>(null);
const isLoading = ref(true);
const isSubmitting = ref(false);
const error = ref("");
const reviewText = ref("");
const isEditMode = ref(false);
const successMessage = ref("");
const closeCountdown = ref<number | null>(null);
let closeTimer: number | null = null;
let countdownTimer: number | null = null;

const isPending = computed(() => review.value?.status === "pending");
const hasDraftChanges = computed(() => {
  if (!review.value) return false;
  return reviewText.value.trim() !== review.value.original_draft_text.trim();
});
const activeMarkdownText = computed(() => {
  if (!review.value) return "";
  if (isPending.value) {
    return isEditMode.value ? reviewText.value : review.value.original_draft_text;
  }
  return reviewText.value;
});
const resolvedPreview = computed(() => {
  const text = review.value?.resolved_output?.text;
  return typeof text === "string" ? text : "";
});

function renderMarkdown(value: string): string {
  const html = marked(value || "", {
    breaks: true,
    gfm: true,
  }) as string;
  return DOMPurify.sanitize(html);
}

const summaryHtml = computed(() => renderMarkdown(review.value?.summary || ""));
const reviewPreviewHtml = computed(() => renderMarkdown(activeMarkdownText.value));
const resolvedPreviewHtml = computed(() => renderMarkdown(resolvedPreview.value));

function openEditMode(): void {
  if (!review.value || !isPending.value || isSubmitting.value) return;
  reviewText.value = review.value.original_draft_text;
  isEditMode.value = true;
}

function cancelEditMode(): void {
  if (!review.value || !isPending.value || isSubmitting.value) return;
  reviewText.value = review.value.original_draft_text;
  isEditMode.value = false;
}

function clearCloseTimers(): void {
  if (closeTimer !== null) {
    window.clearTimeout(closeTimer);
    closeTimer = null;
  }
  if (countdownTimer !== null) {
    window.clearInterval(countdownTimer);
    countdownTimer = null;
  }
}

function attemptCloseTab(): void {
  window.close();
  window.setTimeout(() => {
    window.open("", "_self");
    window.close();
  }, 120);
}

function startCloseCountdown(message: string): void {
  clearCloseTimers();
  successMessage.value = message;
  closeCountdown.value = 3;
  countdownTimer = window.setInterval(() => {
    if (closeCountdown.value === null || closeCountdown.value <= 1) {
      if (countdownTimer !== null) {
        window.clearInterval(countdownTimer);
        countdownTimer = null;
      }
      closeCountdown.value = 0;
      return;
    }
    closeCountdown.value -= 1;
  }, 1000);
  closeTimer = window.setTimeout(() => {
    attemptCloseTab();
  }, 3000);
}

async function loadReview(): Promise<void> {
  isLoading.value = true;
  error.value = "";
  try {
    const data = await hitlApi.get(token.value);
    review.value = data;
    reviewText.value =
      data.edited_text || data.refusal_reason || data.original_draft_text;
    if (data.status !== "pending") {
      isEditMode.value = false;
    }
  } catch (err) {
    const axiosErr = err as {
      response?: { status?: number; data?: { detail?: string } };
    };
    if (axiosErr.response?.status === 404) {
      error.value = "Review request not found.";
    } else if (axiosErr.response?.status === 410 || axiosErr.response?.status === 409) {
      error.value = axiosErr.response?.data?.detail || "This review link is no longer active.";
    } else {
      error.value = axiosErr.response?.data?.detail || "Failed to load review request.";
    }
  } finally {
    isLoading.value = false;
  }
}

async function submitDecision(action: "accept" | "edit" | "refuse"): Promise<void> {
  if (!review.value || !isPending.value || isSubmitting.value) return;
  if (action === "edit" && !reviewText.value.trim()) {
    error.value = "Edited text is required.";
    return;
  }

  isSubmitting.value = true;
  error.value = "";
  try {
    await hitlApi.decide(token.value, {
      action,
      edited_text: action === "edit" ? reviewText.value : undefined,
      refusal_reason:
        action === "refuse" && reviewText.value.trim() !== review.value.original_draft_text.trim()
          ? reviewText.value
          : undefined,
    });
    const resolvedDecision =
      action === "accept" ? "accepted" : action === "edit" ? "edited" : "refused";
    const resolvedReviewText =
      action === "edit"
        ? reviewText.value
        : action === "refuse"
          ? (
              reviewText.value.trim() !== review.value.original_draft_text.trim()
                ? reviewText.value
                : review.value.original_draft_text
            )
          : review.value.original_draft_text;
    review.value = {
      ...review.value,
      status: "resolved",
      decision: resolvedDecision,
      edited_text: action === "edit" ? reviewText.value : review.value.edited_text,
      refusal_reason:
        action === "refuse" && resolvedReviewText !== review.value.original_draft_text
          ? resolvedReviewText
          : review.value.refusal_reason,
      resolved_output: {
        ...review.value.resolved_output,
        text: action === "refuse" ? "" : resolvedReviewText,
        decision: resolvedDecision,
        summary: review.value.summary,
        originalDraft: review.value.original_draft_text,
        reviewText: resolvedReviewText,
        requestId: review.value.request_id,
      },
    };
    reviewText.value = resolvedReviewText;
    isEditMode.value = false;
    localStorage.setItem(
      "heym-hitl-resolution",
      JSON.stringify({
        requestId: review.value.request_id,
        at: Date.now(),
      }),
    );
    const actionLabel =
      action === "accept"
        ? "Accepted"
        : action === "edit"
          ? "Updated and continued"
          : "Refused";
    startCloseCountdown(`${actionLabel} successfully. This tab will close automatically.`);
  } catch (err) {
    const axiosErr = err as {
      response?: { data?: { detail?: string } };
    };
    error.value = axiosErr.response?.data?.detail || "Failed to submit decision.";
  } finally {
    isSubmitting.value = false;
  }
}

onMounted(loadReview);
onUnmounted(() => {
  clearCloseTimers();
});
</script>

<template>
  <div class="min-h-screen bg-muted/20 text-foreground">
    <main class="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <div class="rounded-3xl border border-border/60 bg-background/92 shadow-2xl backdrop-blur">
        <div class="border-b border-border/60 px-6 py-5 sm:px-8">
          <div class="flex flex-wrap items-center gap-3">
            <span class="inline-flex items-center gap-2 rounded-full border border-border/70 bg-muted/50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              <Clock3 class="h-3.5 w-3.5" />
              Human Review
            </span>
            <span
              v-if="review"
              class="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium"
              :class="isPending ? 'bg-amber-500/15 text-amber-600 dark:text-amber-300' : review.status === 'resolved' ? 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300' : 'bg-destructive/10 text-destructive'"
            >
              <CheckCircle2
                v-if="review.status === 'resolved'"
                class="h-3.5 w-3.5"
              />
              <ShieldAlert
                v-else-if="review.status === 'expired'"
                class="h-3.5 w-3.5"
              />
              <Clock3
                v-else
                class="h-3.5 w-3.5"
              />
              {{ review.status }}
            </span>
          </div>
          <h1 class="mt-4 text-2xl font-semibold tracking-tight sm:text-3xl">
            {{ review?.workflow_name || "Loading review..." }}
          </h1>
          <p class="mt-2 text-sm text-muted-foreground">
            {{ review?.agent_label || "Agent" }} is waiting for a decision before the workflow continues.
          </p>
        </div>

        <div
          v-if="isLoading"
          class="flex items-center justify-center gap-3 px-6 py-16 text-muted-foreground"
        >
          <Loader2 class="h-5 w-5 animate-spin" />
          Loading review request...
        </div>

        <div
          v-else-if="error && !review"
          class="space-y-4 px-6 py-12 sm:px-8"
        >
          <div class="flex items-center gap-3 text-destructive">
            <XCircle class="h-5 w-5" />
            <span class="text-sm font-medium">{{ error }}</span>
          </div>
          <Button
            variant="outline"
            class="gap-2"
            @click="loadReview"
          >
            <RefreshCcw class="h-4 w-4" />
            Retry
          </Button>
        </div>

        <div
          v-else-if="review"
          class="space-y-6 px-6 py-6 sm:px-8"
        >
          <div
            v-if="successMessage"
            class="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 px-4 py-3 text-sm text-emerald-700 dark:text-emerald-300"
          >
            <div class="flex items-center gap-2 font-medium">
              <CheckCircle2 class="h-4 w-4" />
              {{ successMessage }}
            </div>
            <p
              v-if="closeCountdown !== null"
              class="mt-1 text-xs text-emerald-700/80 dark:text-emerald-300/80"
            >
              Closing in {{ closeCountdown }} second<span v-if="closeCountdown !== 1">s</span>.
            </p>
          </div>

          <div
            v-if="error"
            class="rounded-2xl border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive"
          >
            {{ error }}
          </div>

          <section class="rounded-2xl border border-border/60 bg-muted/10 p-4">
            <Label class="text-xs uppercase tracking-[0.16em] text-muted-foreground">Summary</Label>
            <!-- eslint-disable vue/no-v-html -->
            <div
              class="hitl-markdown prose prose-sm mt-3 max-w-none min-w-0 overflow-hidden text-foreground dark:prose-invert prose-p:text-muted-foreground prose-headings:text-foreground prose-strong:text-foreground prose-a:text-primary"
              v-html="summaryHtml"
            />
            <!-- eslint-enable vue/no-v-html -->
          </section>

          <section class="rounded-2xl border border-border/60 bg-muted/20 p-4">
            <div class="flex items-center justify-between gap-3">
              <Label class="text-xs uppercase tracking-[0.16em] text-muted-foreground">Markdown Review</Label>
              <span
                v-if="isPending"
                class="text-[11px] font-medium text-muted-foreground"
              >
                {{ isEditMode ? "Editing draft" : "Read-only until Edit is selected" }}
              </span>
            </div>
            <!-- eslint-disable vue/no-v-html -->
            <div
              class="hitl-markdown prose prose-sm mt-3 max-w-none min-w-0 overflow-hidden text-foreground dark:prose-invert prose-p:text-muted-foreground prose-headings:text-foreground prose-strong:text-foreground prose-a:text-primary"
              v-html="reviewPreviewHtml"
            />
            <!-- eslint-enable vue/no-v-html -->
          </section>

          <section
            v-if="isPending && isEditMode"
            class="space-y-3 rounded-2xl border border-border/60 bg-muted/10 p-4"
          >
            <Label>Edit Markdown</Label>
            <Textarea
              v-model="reviewText"
              :rows="14"
              :readonly="isSubmitting"
              placeholder="Revise the Markdown plan, then continue."
            />
            <p class="text-xs text-muted-foreground">
              The live preview above updates as you edit.
            </p>
            <div
              v-if="hasDraftChanges"
              class="rounded-2xl border border-amber-500/20 bg-amber-500/5 px-4 py-3 text-xs text-amber-700 dark:text-amber-300"
            >
              The Markdown changed. Submit the edit to continue with this revised plan.
            </div>
          </section>

          <section
            v-if="review.status === 'resolved'"
            class="rounded-2xl border border-emerald-500/20 bg-emerald-500/5 p-4"
          >
            <Label class="text-xs uppercase tracking-[0.16em] text-emerald-600 dark:text-emerald-300">Resolved Output</Label>
            <p class="mt-2 text-sm text-muted-foreground">
              Decision: {{ review.decision || "resolved" }}
            </p>
            <!-- eslint-disable vue/no-v-html -->
            <div
              v-if="resolvedPreview"
              class="hitl-markdown prose prose-sm mt-3 max-w-none min-w-0 overflow-hidden text-foreground dark:prose-invert prose-p:text-muted-foreground prose-headings:text-foreground prose-strong:text-foreground prose-a:text-primary"
              v-html="resolvedPreviewHtml"
            />
            <!-- eslint-enable vue/no-v-html -->
          </section>

          <div class="flex flex-wrap gap-3 pt-2">
            <Button
              v-if="isPending && !isEditMode"
              :disabled="isSubmitting"
              class="gap-2"
              @click="submitDecision('accept')"
            >
              <Loader2
                v-if="isSubmitting"
                class="h-4 w-4 animate-spin"
              />
              <CheckCircle2
                v-else
                class="h-4 w-4"
              />
              Accept
            </Button>
            <Button
              v-if="isPending && !isEditMode"
              variant="secondary"
              :disabled="isSubmitting"
              class="gap-2"
              @click="openEditMode"
            >
              Edit
            </Button>
            <Button
              v-if="isPending && isEditMode"
              variant="outline"
              :disabled="isSubmitting"
              class="gap-2"
              @click="cancelEditMode"
            >
              Cancel Edit
            </Button>
            <Button
              v-if="isPending && isEditMode"
              variant="secondary"
              :disabled="isSubmitting || !hasDraftChanges"
              class="gap-2"
              @click="submitDecision('edit')"
            >
              Edit &amp; Continue
            </Button>
            <Button
              v-if="isPending"
              variant="destructive"
              :disabled="isSubmitting"
              class="gap-2"
              @click="submitDecision('refuse')"
            >
              Refuse
            </Button>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>

<style scoped>
.hitl-markdown {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.hitl-markdown :deep(pre) {
  max-width: 100%;
  overflow-x: auto;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  word-break: break-word;
}

.hitl-markdown :deep(pre code) {
  white-space: inherit;
  overflow-wrap: inherit;
  word-break: inherit;
}

.hitl-markdown :deep(code) {
  overflow-wrap: anywhere;
  word-break: break-word;
}

.hitl-markdown :deep(table) {
  display: block;
  max-width: 100%;
  overflow-x: auto;
}
</style>
