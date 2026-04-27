<script setup lang="ts">
import { Check, ChevronDown, Copy, FileText, Loader2, Send, Square, Trash2, Wand2 } from "lucide-vue-next";

import { useDocsChatDialog } from "@/components/Docs/useDocsChatDialog";
import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";

interface Props { open: boolean; docPath: string | null }

const props = defineProps<Props>();
const emit = defineEmits<{ (e: "close"): void }>();

const {
  credentials,
  models,
  selectedCredentialId,
  selectedModel,
  loadingModels,
  modelsLoadFailed,
  messages,
  inputText,
  streaming,
  steps,
  hasClearableContent,
  copiedMessageId,
  messagesContainer,
  chatInputRef,
  renderMarkdown,
  clearChat,
  copyMessageContent,
  handleSubmit,
  stopStreaming,
  handleKeydown,
  handleClose,
} = useDocsChatDialog(props, () => emit("close"));
</script>

<template>
  <Dialog
    :open="open"
    title="Chat with Docs"
    size="4xl"
    @close="handleClose"
  >
    <template #header-trailing>
      <Button
        v-if="hasClearableContent"
        variant="outline"
        size="sm"
        @click="clearChat"
      >
        <Trash2 class="h-4 w-4" />
        Clear
      </Button>
    </template>
    <div class="flex h-[70vh] min-h-[420px] min-w-0 flex-col">
      <div class="grid grid-cols-2 gap-2 shrink-0 border-b border-border/50 pb-3">
        <div class="relative min-w-0">
          <select
            v-model="selectedCredentialId"
            class="h-10 w-full cursor-pointer appearance-none truncate rounded-lg border border-input bg-background pl-3 pr-9 text-sm"
          >
            <option
              value=""
              disabled
            >
              {{ credentials.length === 0 ? "No credentials" : "Select credential..." }}
            </option>
            <option
              v-for="credential in credentials"
              :key="credential.id"
              :value="credential.id"
            >
              {{ credential.name }}
            </option>
          </select>
          <ChevronDown class="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        </div>
        <div class="relative min-w-0">
          <select
            v-model="selectedModel"
            :disabled="!selectedCredentialId || loadingModels || modelsLoadFailed"
            class="h-10 w-full cursor-pointer appearance-none truncate rounded-lg border border-input bg-background pl-3 pr-9 text-sm disabled:cursor-not-allowed disabled:opacity-50"
          >
            <option
              value=""
              disabled
            >
              {{ loadingModels ? "Loading..." : modelsLoadFailed ? "Failed to load" : !selectedCredentialId ? "Select credential first" : "Select model..." }}
            </option>
            <option
              v-for="model in models"
              :key="model.id"
              :value="model.id"
            >
              {{ model.name }}
            </option>
          </select>
          <Loader2
            v-if="loadingModels"
            class="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 animate-spin text-muted-foreground"
          />
          <ChevronDown
            v-else
            class="pointer-events-none absolute right-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground"
          />
        </div>
      </div>

      <div
        ref="messagesContainer"
        :class="['flex-1 min-h-0 overflow-y-auto py-4', messages.length === 0 ? 'flex items-center justify-center' : 'space-y-3']"
      >
        <div
          v-if="messages.length === 0"
          class="flex flex-col items-center gap-3 px-4 text-center text-muted-foreground"
        >
          <Wand2 class="h-10 w-10 opacity-50" />
          <p class="text-sm">
            Ask anything about the docs
          </p>
        </div>
        <template v-else>
          <div
            v-for="message in messages"
            :key="message.id"
            :class="['flex', message.role === 'user' ? 'justify-end' : 'justify-start']"
          >
            <div :class="['relative max-w-[85%] break-words rounded-2xl px-4 py-3 pr-12 text-sm', message.role === 'user' ? 'bg-primary text-primary-foreground' : 'border border-border/50 bg-muted/80']">
              <button
                type="button"
                class="absolute right-2 top-2 flex min-h-8 min-w-8 items-center justify-center rounded-lg text-current opacity-70 transition-colors hover:bg-black/10 hover:opacity-100 dark:hover:bg-white/10"
                :title="copiedMessageId === message.id ? 'Copied!' : 'Copy'"
                :aria-label="copiedMessageId === message.id ? 'Copied' : 'Copy message'"
                @click.stop="copyMessageContent(message)"
              >
                <Check
                  v-if="copiedMessageId === message.id"
                  class="h-4 w-4 text-green-600 dark:text-green-400"
                />
                <Copy
                  v-else
                  class="h-4 w-4"
                />
              </button>
              <template v-if="message.role === 'assistant'">
                <div
                  v-if="steps.length > 0 && messages.at(-1)?.id === message.id"
                  class="mb-3 space-y-1.5"
                >
                  <div
                    v-for="(step, index) in steps"
                    :key="index"
                    class="flex items-center gap-2 text-xs text-muted-foreground"
                  >
                    <Loader2
                      v-if="streaming && index === steps.length - 1"
                      class="h-3.5 w-3.5 shrink-0 animate-spin"
                    />
                    <span
                      v-else
                      class="flex h-3.5 w-3.5 shrink-0 items-center justify-center rounded-full bg-primary/20"
                    ><span class="text-[10px] text-primary">✓</span></span>
                    <span>{{ step }}</span>
                  </div>
                </div>
                <!-- eslint-disable vue/no-v-html -->
                <div
                  v-if="message.content"
                  class="markdown-content max-w-none break-words"
                  v-html="renderMarkdown(message.content)"
                />
                <!-- eslint-enable vue/no-v-html -->
                <div
                  v-else-if="streaming && messages.at(-1)?.id === message.id"
                  class="flex items-center gap-2 text-muted-foreground"
                >
                  <Loader2 class="h-4 w-4 shrink-0 animate-spin" />
                  <span>{{ steps.length > 0 ? "Preparing response..." : "Thinking..." }}</span>
                </div>
              </template>
              <p
                v-else
                class="overflow-wrap-anywhere whitespace-pre-wrap"
              >
                {{ message.content }}
              </p>
            </div>
          </div>
        </template>
      </div>

      <div class="shrink-0 border-t border-border/50 pt-3">
        <div
          v-if="docPath"
          class="mb-2 inline-flex items-center gap-1.5 rounded-full bg-muted/60 px-2.5 py-1 text-xs text-muted-foreground"
        >
          <FileText class="h-3.5 w-3.5 shrink-0" />
          <span class="font-mono">{{ docPath }}</span>
        </div>
        <form
          class="flex min-h-[52px] items-center gap-2 rounded-2xl border border-border/40 bg-muted/40 px-3 py-2 transition-colors focus-within:border-primary/30"
          @submit.prevent="handleSubmit"
        >
          <textarea
            ref="chatInputRef"
            v-model="inputText"
            :disabled="streaming || !selectedCredentialId || !selectedModel || modelsLoadFailed"
            rows="1"
            placeholder="Ask about the docs..."
            class="min-h-[36px] max-h-32 flex-1 resize-none border-0 bg-transparent px-1 py-2 text-sm leading-5 placeholder:text-muted-foreground focus:outline-none disabled:opacity-50"
            @keydown="handleKeydown"
          />
          <Button
            v-if="!streaming"
            type="submit"
            variant="gradient"
            size="icon"
            :disabled="!inputText.trim() || !selectedCredentialId || !selectedModel || modelsLoadFailed"
            class="h-9 w-9 shrink-0 rounded-xl"
          >
            <Send class="h-4 w-4" />
          </Button>
          <Button
            v-else
            type="button"
            variant="destructive"
            size="icon"
            class="h-9 w-9 shrink-0 rounded-xl"
            @click="stopStreaming"
          >
            <Square class="h-4 w-4" />
          </Button>
        </form>
      </div>
    </div>
  </Dialog>
</template>

<style scoped>
.markdown-content :deep(h1), .markdown-content :deep(h2), .markdown-content :deep(h3), .markdown-content :deep(h4) { margin: 0.75em 0 0.4em; font-weight: 600; }
.markdown-content :deep(p) { margin: 0.4em 0; }
.markdown-content :deep(ul), .markdown-content :deep(ol) { margin-top: 0.4em; padding-left: 1.5em; }
.markdown-content :deep(code) { background: hsl(var(--muted) / 0.6); border-radius: 0.25rem; padding: 0.125em 0.375em; font-size: 0.875em; }
.markdown-content :deep(pre) { background: hsl(var(--muted) / 0.6); border-radius: 0.5rem; margin-top: 0.5em; overflow-x: auto; padding: 0.75em; }
.markdown-content :deep(pre code) { background: transparent; padding: 0; }
.markdown-content :deep(a) { color: hsl(var(--primary)); text-decoration: underline; }
.overflow-wrap-anywhere { overflow-wrap: anywhere; word-break: break-word; }
</style>
