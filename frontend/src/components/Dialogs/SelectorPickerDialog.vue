<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from "vue";
import { Check, Copy, ExternalLink, MousePointerClick } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";

const STORAGE_KEY = "heym_picker_selector";
const STALE_MS = 60_000;

interface Props {
  open: boolean;
  initialUrl?: string;
}

const props = defineProps<Props>();

const emit = defineEmits<{
  (e: "close"): void;
  (e: "select", selector: string): void;
}>();

const url = ref("");
const error = ref("");
const copied = ref(false);
const pickedSelector = ref<string | null>(null);

const bookmarkletHref = computed(() => {
  const base = typeof window !== "undefined" ? window.location.origin : "";
  const scriptUrl = base + "/picker-inject.js";
  return (
    "javascript:(function(){var s=document.createElement('script');s.src='" +
    scriptUrl +
    "';document.body.appendChild(s);})();"
  );
});

function handleStorageEvent(e: StorageEvent): void {
  if (e.key !== STORAGE_KEY || !e.newValue || !props.open) return;
  try {
    const data = JSON.parse(e.newValue) as { selector: string; ts: number };
    if (Date.now() - data.ts > STALE_MS) return;
    pickedSelector.value = data.selector;
    error.value = "";
    window.focus();
  } catch {
    /* ignore parse errors */
  }
}

watch(
  () => props.open,
  (open) => {
    if (open) {
      url.value = props.initialUrl || "";
      error.value = "";
      copied.value = false;
      pickedSelector.value = null;
      if (typeof window !== "undefined") {
        window.addEventListener("storage", handleStorageEvent);
      }
    } else {
      if (typeof window !== "undefined") {
        window.removeEventListener("storage", handleStorageEvent);
      }
    }
  },
  { immediate: true }
);

onBeforeUnmount(() => {
  if (typeof window !== "undefined") {
    window.removeEventListener("storage", handleStorageEvent);
  }
});

function openPage(): void {
  const u = url.value.trim();
  if (!u) {
    error.value = "Enter a URL first";
    return;
  }
  if (!u.startsWith("http://") && !u.startsWith("https://")) {
    error.value = "URL must start with http:// or https://";
    return;
  }
  error.value = "";
  window.open(u, "_blank");
}

function copyBookmarklet(): void {
  navigator.clipboard.writeText(bookmarkletHref.value).then(() => {
    copied.value = true;
    setTimeout(() => { copied.value = false; }, 2000);
  });
}

function getSelector(): void {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      error.value = "No selector found. Run the bookmarklet and click an element first.";
      return;
    }
    const data = JSON.parse(raw) as { selector: string; ts: number };
    if (Date.now() - data.ts > STALE_MS) {
      error.value = "Selector expired. Run the bookmarklet and click an element again.";
      return;
    }
    error.value = "";
    emit("select", data.selector);
    emit("close");
  } catch {
    error.value = "Failed to read selector.";
  }
}

function useSelector(): void {
  if (!pickedSelector.value) return;
  emit("select", pickedSelector.value);
  emit("close");
}

function close(): void {
  emit("close");
}
</script>

<template>
  <Dialog
    :open="open"
    title="Pick selector from page"
    size="md"
    @close="close"
  >
    <div class="space-y-4">
      <div class="space-y-2">
        <Label>Page URL</Label>
        <div class="flex gap-2">
          <Input
            :model-value="url"
            placeholder="https://example.com"
            class="font-mono text-sm"
            @update:model-value="url = $event"
            @keydown.enter="openPage"
          />
          <Button
            variant="outline"
            size="icon"
            title="Open page in new tab"
            @click="openPage"
          >
            <ExternalLink class="h-4 w-4" />
          </Button>
        </div>
      </div>

      <div class="space-y-2 rounded-lg border bg-muted/30 p-3">
        <Label class="flex items-center gap-2 text-sm">
          <MousePointerClick class="h-4 w-4" />
          Bookmarklet
        </Label>
        <p class="text-xs text-muted-foreground">
          Drag this link to your bookmarks bar, or copy it. On the target page, click the bookmarklet, then click the
          element you want.
        </p>
        <div class="flex items-center gap-2">
          <a
            :href="bookmarkletHref"
            class="flex-1 truncate rounded border bg-background px-3 py-2 text-xs font-mono text-muted-foreground hover:text-foreground"
          >
            Pick from page
          </a>
          <Button
            variant="outline"
            size="sm"
            @click="copyBookmarklet"
          >
            <Copy class="h-4 w-4 mr-1" />
            {{ copied ? "Copied!" : "Copy" }}
          </Button>
        </div>
      </div>

      <ol class="list-decimal list-inside space-y-1 text-sm text-muted-foreground">
        <li>Open the page (use the button above)</li>
        <li>Click the bookmarklet on that page</li>
        <li>Click the element you want to select</li>
        <li>Selection appears here automatically, or click "Get selector"</li>
      </ol>

      <div
        v-if="pickedSelector"
        class="flex flex-col gap-2 rounded-lg border border-green-500/50 bg-green-500/10 p-3"
      >
        <Label class="flex items-center gap-2 text-sm text-green-700 dark:text-green-400">
          <Check class="h-4 w-4" />
          Selection made
        </Label>
        <code class="break-all rounded bg-background px-2 py-1.5 font-mono text-xs">
          {{ pickedSelector }}
        </code>
      </div>

      <p
        v-if="error"
        class="text-sm text-destructive"
      >
        {{ error }}
      </p>

      <div class="flex justify-end gap-2 pt-2">
        <Button
          variant="outline"
          @click="close"
        >
          Cancel
        </Button>
        <Button
          v-if="!pickedSelector"
          @click="getSelector"
        >
          Get selector
        </Button>
        <Button
          v-else
          @click="useSelector"
        >
          Use
        </Button>
      </div>
    </div>
  </Dialog>
</template>
