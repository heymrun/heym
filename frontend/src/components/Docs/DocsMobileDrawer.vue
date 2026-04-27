<script setup lang="ts">
import Button from "@/components/ui/Button.vue";
import DocsSidebar from "@/components/Docs/DocsSidebar.vue";

interface Props {
  open: boolean;
}

defineProps<Props>();

const emit = defineEmits<{
  (e: "update:open", value: boolean): void;
  (e: "navigate"): void;
}>();

function close(): void {
  emit("update:open", false);
}

function onNavigate(): void {
  emit("navigate");
  close();
}
</script>

<template>
  <Teleport to="body">
    <Transition name="drawer">
      <div
        v-if="open"
        class="fixed inset-0 z-50 flex"
        role="dialog"
        aria-modal="true"
        aria-label="Documentation menu"
      >
        <div
          class="absolute inset-0 bg-background/80 backdrop-blur-sm"
          aria-hidden="true"
          @click="close"
        />
        <div
          class="relative w-64 max-w-[85vw] h-full bg-card border-r border-border/60 shadow-xl flex flex-col"
          @click.stop
        >
          <div class="p-3 border-b border-border/40 flex items-center justify-between shrink-0">
            <span class="font-semibold text-foreground">Documentation</span>
            <Button
              variant="ghost"
              size="icon"
              class="h-9 w-9"
              aria-label="Close menu"
              @click="close"
            >
              <span class="text-lg leading-none">×</span>
            </Button>
          </div>
          <div class="flex-1 overflow-y-auto overflow-x-hidden min-h-0">
            <DocsSidebar @navigate="onNavigate" />
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<style scoped>
.drawer-enter-active,
.drawer-leave-active {
  transition: opacity 0.2s ease;
}
.drawer-enter-active .relative,
.drawer-leave-active .relative {
  transition: transform 0.25s cubic-bezier(0.22, 1, 0.36, 1);
}
.drawer-enter-from,
.drawer-leave-to {
  opacity: 0;
}
.drawer-enter-from .relative,
.drawer-leave-to .relative {
  transform: translateX(-100%);
}
</style>
