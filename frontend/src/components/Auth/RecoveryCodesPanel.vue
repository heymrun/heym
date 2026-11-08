<script setup lang="ts">
import { ref } from "vue";
import { Check, Copy, Download } from "lucide-vue-next";

import Button from "@/components/ui/Button.vue";

const props = defineProps<{
  codes: string[];
  confirmLabel?: string;
}>();

const emit = defineEmits<{
  confirm: [];
}>();

const copied = ref(false);

function codesText(): string {
  return `Heym recovery codes\nEach code works once.\n\n${props.codes.join("\n")}\n`;
}

async function copyCodes(): Promise<void> {
  await navigator.clipboard.writeText(codesText());
  copied.value = true;
  window.setTimeout(() => {
    copied.value = false;
  }, 1500);
}

function downloadCodes(): void {
  const url = URL.createObjectURL(new Blob([codesText()], { type: "text/plain" }));
  const link = document.createElement("a");
  link.href = url;
  link.download = "heym-recovery-codes.txt";
  link.click();
  URL.revokeObjectURL(url);
}
</script>

<template>
  <div
    class="space-y-4"
    data-testid="mfa-recovery-codes"
  >
    <div class="space-y-1">
      <h3 class="text-base font-semibold">
        Save your recovery codes
      </h3>
      <p class="text-sm text-muted-foreground">
        If you lose your phone, each code signs you in once. They are shown only now.
      </p>
    </div>
    <ul class="grid grid-cols-2 gap-2 rounded-lg border border-border bg-muted/30 p-3 font-mono text-sm">
      <li
        v-for="code in codes"
        :key="code"
        class="text-center"
      >
        {{ code }}
      </li>
    </ul>
    <div class="flex flex-wrap gap-2">
      <Button
        type="button"
        variant="outline"
        size="sm"
        @click="copyCodes"
      >
        <Check
          v-if="copied"
          class="w-4 h-4 mr-1"
        />
        <Copy
          v-else
          class="w-4 h-4 mr-1"
        />
        {{ copied ? "Copied" : "Copy" }}
      </Button>
      <Button
        type="button"
        variant="outline"
        size="sm"
        @click="downloadCodes"
      >
        <Download class="w-4 h-4 mr-1" />
        Download
      </Button>
    </div>
    <Button
      type="button"
      class="w-full"
      @click="emit('confirm')"
    >
      {{ confirmLabel ?? "I saved my codes" }}
    </Button>
  </div>
</template>
