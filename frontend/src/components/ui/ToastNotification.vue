<script setup lang="ts">
import { CheckCircle, XCircle, Info } from "lucide-vue-next";
import { useToast } from "@/composables/useToast";

const { toastMessage, toastType, toastVisible, hideToast } = useToast();
</script>

<template>
  <Teleport to="body">
    <Transition
      enter-active-class="transition-all duration-300 ease-out"
      leave-active-class="transition-all duration-200 ease-in"
      enter-from-class="opacity-0 translate-y-2 scale-95"
      enter-to-class="opacity-100 translate-y-0 scale-100"
      leave-from-class="opacity-100 translate-y-0 scale-100"
      leave-to-class="opacity-0 translate-y-2 scale-95"
    >
      <div
        v-if="toastVisible"
        :class="[
          'fixed bottom-6 right-6 z-[9999] flex items-center gap-3 px-4 py-3 rounded-xl shadow-2xl max-w-sm border',
          toastType === 'success' && 'border-emerald-500 bg-emerald-500 text-white',
          toastType === 'error' && 'bg-red-950/90 border-red-500/30 text-red-100',
          toastType === 'info' && 'bg-primary/10 border-primary/30 text-foreground',
        ]"
        role="alert"
      >
        <CheckCircle
          v-if="toastType === 'success'"
          class="w-5 h-5 shrink-0 text-white"
        />
        <XCircle
          v-else-if="toastType === 'error'"
          class="w-5 h-5 text-red-400 shrink-0"
        />
        <Info
          v-else
          class="w-5 h-5 text-primary shrink-0"
        />
        <span class="text-sm font-medium leading-snug">{{ toastMessage }}</span>
        <button
          class="ml-1 transition-opacity hover:opacity-100"
          :class="toastType === 'success' ? 'opacity-80' : 'opacity-60'"
          type="button"
          @click="hideToast"
        >
          <span class="sr-only">Close</span>
          <svg
            class="w-4 h-4"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            viewBox="0 0 24 24"
          >
            <path
              d="M6 18L18 6M6 6l12 12"
              stroke-linecap="round"
              stroke-linejoin="round"
            />
          </svg>
        </button>
      </div>
    </Transition>
  </Teleport>
</template>
