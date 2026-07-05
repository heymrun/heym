<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import DOMPurify from "dompurify";
import { marked } from "marked";
import { useRoute } from "vue-router";
import { CheckCircle2, Clock3, Loader2, ShieldAlert, Terminal } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Label from "@/components/ui/Label.vue";
import Textarea from "@/components/ui/Textarea.vue";
import { codexFollowupApi } from "@/services/api";
import type { CodexFollowup } from "@/types/workflow";

const route = useRoute();
const token = computed(() => String(route.params.token || ""));

const followup = ref<CodexFollowup | null>(null);
const answerText = ref("");
const isLoading = ref(true);
const isSubmitting = ref(false);
const error = ref("");
const successMessage = ref("");

const isPending = computed(() => followup.value?.status === "pending");
const submitDisabled = computed(
  () => !isPending.value || isSubmitting.value || !answerText.value.trim(),
);

function renderMarkdown(value: string): string {
  const html = marked(value || "", {
    breaks: true,
    gfm: true,
  }) as string;
  return DOMPurify.sanitize(html);
}

const summaryHtml = computed(() => renderMarkdown(followup.value?.summary || ""));
const questionHtml = computed(() => renderMarkdown(followup.value?.question || ""));

async function loadFollowup(): Promise<void> {
  isLoading.value = true;
  error.value = "";
  try {
    const data = await codexFollowupApi.get(token.value);
    followup.value = data;
    answerText.value = data.answer_text || "";
  } catch (err) {
    const axiosErr = err as {
      response?: { status?: number; data?: { detail?: string } };
    };
    if (axiosErr.response?.status === 404) {
      error.value = "Codex follow-up request not found.";
    } else if (axiosErr.response?.status === 410 || axiosErr.response?.status === 409) {
      error.value = axiosErr.response?.data?.detail || "This follow-up link is no longer active.";
    } else {
      error.value = axiosErr.response?.data?.detail || "Failed to load Codex follow-up.";
    }
  } finally {
    isLoading.value = false;
  }
}

async function submitAnswer(): Promise<void> {
  if (!followup.value || submitDisabled.value) {
    return;
  }
  isSubmitting.value = true;
  error.value = "";
  successMessage.value = "";
  try {
    await codexFollowupApi.answer(token.value, {
      answer_text: answerText.value.trim(),
    });
    followup.value = {
      ...followup.value,
      status: "answered",
      answer_text: answerText.value.trim(),
      answered_at: new Date().toISOString(),
      resolved_output: {
        ...followup.value.resolved_output,
        answerText: answerText.value.trim(),
        requestId: followup.value.request_id,
      },
    };
    successMessage.value = "Answer received. Codex will continue the run.";
  } catch (err) {
    const axiosErr = err as {
      response?: { data?: { detail?: string } };
    };
    error.value = axiosErr.response?.data?.detail || "Failed to submit answer.";
  } finally {
    isSubmitting.value = false;
  }
}

onMounted(loadFollowup);
</script>

<template>
  <div class="min-h-screen bg-muted/20 text-foreground">
    <main class="mx-auto max-w-4xl px-4 py-10 sm:px-6">
      <div class="rounded-2xl border border-border/60 bg-background/95 shadow-xl">
        <div class="border-b border-border/60 px-6 py-5 sm:px-8">
          <div class="flex flex-wrap items-center gap-3">
            <span class="inline-flex items-center gap-2 rounded-full border border-border/70 bg-muted/50 px-3 py-1 text-xs font-medium uppercase tracking-[0.18em] text-muted-foreground">
              <Terminal class="h-3.5 w-3.5" />
              Codex Follow-up
            </span>
            <span
              v-if="followup"
              class="inline-flex items-center gap-2 rounded-full px-3 py-1 text-xs font-medium"
              :class="isPending ? 'bg-amber-500/15 text-amber-600 dark:text-amber-300' : 'bg-emerald-500/15 text-emerald-600 dark:text-emerald-300'"
            >
              <Clock3
                v-if="isPending"
                class="h-3.5 w-3.5"
              />
              <CheckCircle2
                v-else
                class="h-3.5 w-3.5"
              />
              {{ isPending ? "Waiting for answer" : "Answered" }}
            </span>
          </div>
          <h1 class="mt-4 text-2xl font-semibold tracking-tight">
            {{ followup?.codex_label || "Codex" }}
          </h1>
          <p
            v-if="followup"
            class="mt-1 text-sm text-muted-foreground"
          >
            {{ followup.workflow_name }} · {{ followup.repository_url }}
          </p>
        </div>

        <div class="px-6 py-6 sm:px-8">
          <div
            v-if="isLoading"
            class="flex items-center gap-2 text-sm text-muted-foreground"
          >
            <Loader2 class="h-4 w-4 animate-spin" />
            Loading follow-up...
          </div>

          <div
            v-else-if="error && !followup"
            class="flex items-start gap-3 rounded-xl border border-destructive/30 bg-destructive/5 p-4 text-sm text-destructive"
          >
            <ShieldAlert class="mt-0.5 h-4 w-4 shrink-0" />
            <span>{{ error }}</span>
          </div>

          <div
            v-else-if="followup"
            class="space-y-6"
          >
            <section
              v-if="followup.summary"
              class="space-y-2"
            >
              <Label>Summary</Label>
              <div
                class="prose prose-sm max-w-none text-muted-foreground dark:prose-invert"
                v-html="summaryHtml"
              />
            </section>

            <section class="space-y-2">
              <Label>Question</Label>
              <div
                class="prose prose-sm max-w-none rounded-xl border border-border/60 bg-muted/30 p-4 dark:prose-invert"
                v-html="questionHtml"
              />
            </section>

            <section class="space-y-2">
              <Label for="codex-followup-answer">Answer</Label>
              <Textarea
                id="codex-followup-answer"
                v-model="answerText"
                :disabled="!isPending || isSubmitting"
                :rows="7"
                placeholder="Add the missing detail Codex asked for..."
              />
            </section>

            <div
              v-if="error"
              class="rounded-xl border border-destructive/30 bg-destructive/5 p-3 text-sm text-destructive"
            >
              {{ error }}
            </div>

            <div
              v-if="successMessage"
              class="rounded-xl border border-emerald-500/30 bg-emerald-500/10 p-3 text-sm text-emerald-700 dark:text-emerald-300"
            >
              {{ successMessage }}
            </div>

            <div class="flex justify-end">
              <Button
                type="button"
                :loading="isSubmitting"
                :disabled="submitDisabled"
                @click="submitAnswer"
              >
                Submit Answer
              </Button>
            </div>
          </div>
        </div>
      </div>
    </main>
  </div>
</template>
