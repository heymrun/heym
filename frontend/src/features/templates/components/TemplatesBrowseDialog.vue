<script setup lang="ts">
import { onUnmounted, ref, watch } from "vue";
import { ExternalLink, Globe, X } from "lucide-vue-next";

interface Props {
  open: boolean;
}

const props = defineProps<Props>();
const emit = defineEmits<{ close: [] }>();

const iframeLoaded = ref(false);

const fallback = "https://heym.run";
const raw = import.meta.env.VITE_HEYM_WEB_URL?.trim() ?? "";
let base = raw || fallback;
if (import.meta.env.PROD && raw) {
  try {
    const { hostname } = new URL(/^https?:\/\//i.test(raw) ? raw : `https://${raw}`);
    if (hostname === "localhost" || hostname === "127.0.0.1") base = fallback;
  } catch {
    base = fallback;
  }
}
const templatesBrowseIframeSrc = `${base.replace(/\/$/, "")}/templates/embed`;
const templatesPageUrl = `${base.replace(/\/$/, "")}/templates`;

function handleLoad(): void {
  iframeLoaded.value = true;
}

function handleKeydown(e: KeyboardEvent): void {
  if (e.key === "Escape" && props.open) {
    e.preventDefault();
    emit("close");
  }
}

watch(
  () => props.open,
  (open) => {
    document.body.style.overflow = open ? "hidden" : "";
    if (!open) {
      iframeLoaded.value = false;
    }
    if (open) {
      window.addEventListener("keydown", handleKeydown, true);
    } else {
      window.removeEventListener("keydown", handleKeydown, true);
    }
  },
  { immediate: true },
);

onUnmounted(() => {
  window.removeEventListener("keydown", handleKeydown, true);
  document.body.style.overflow = "";
});
</script>

<template>
  <Teleport to="body">
    <Transition name="browse-dialog">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6"
      >
        <div
          class="absolute inset-0 bg-black/65 backdrop-blur-md"
          aria-hidden="true"
          @click="emit('close')"
        />

        <div
          class="relative z-10 flex w-full max-w-6xl flex-col overflow-hidden rounded-2xl border border-border/60 bg-card shadow-xl"
          style="
            box-shadow:
              0 0 0 1px hsl(var(--border) / 0.5),
              0 0 1px hsl(0 0% 0% / 0.0125);
          "
          role="dialog"
          aria-modal="true"
          aria-labelledby="browse-public-templates-title"
          @click.stop
        >
          <div
            class="flex shrink-0 items-center justify-between gap-4 border-b border-border/40 px-5 py-4"
          >
            <div class="flex min-w-0 items-center gap-2.5">
              <Globe class="h-5 w-5 shrink-0 text-primary" />
              <h2
                id="browse-public-templates-title"
                class="truncate text-base font-semibold text-foreground"
              >
                Browse Public Templates
              </h2>
            </div>
            <div class="flex shrink-0 items-center gap-1">
              <a
                :href="templatesPageUrl"
                target="_blank"
                rel="noopener noreferrer"
                class="rounded-xl p-2 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
                title="Open templates page"
              >
                <ExternalLink class="h-5 w-5" />
              </a>
              <button
                class="rounded-xl p-2 text-muted-foreground transition-colors hover:bg-muted/60 hover:text-foreground"
                type="button"
                @click="emit('close')"
              >
                <X class="h-5 w-5" />
              </button>
            </div>
          </div>

          <div
            class="relative min-h-[min(70vh,640px)] w-full flex-1 bg-muted/15 p-3 sm:p-4"
          >
            <div
              v-if="!iframeLoaded"
              class="absolute inset-0 z-10 flex items-center justify-center bg-card/90"
            >
              <div
                class="h-8 w-8 animate-spin rounded-full border-2 border-primary border-t-transparent"
              />
            </div>

            <iframe
              :src="templatesBrowseIframeSrc"
              class="h-full min-h-[min(64vh,600px)] w-full rounded-xl border border-border/40 bg-background"
              :class="iframeLoaded ? 'opacity-100' : 'pointer-events-none opacity-0'"
              title="Heym Public Templates"
              allow="clipboard-read; clipboard-write"
              @load="handleLoad"
            />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.browse-dialog-enter-active,
.browse-dialog-leave-active {
  transition: opacity 0.2s ease;
}

.browse-dialog-enter-from,
.browse-dialog-leave-to {
  opacity: 0;
}
</style>
