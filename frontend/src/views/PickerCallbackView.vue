<script setup lang="ts">
import { onMounted } from "vue";
import { useRoute } from "vue-router";

const STORAGE_KEY = "heym_picker_selector";

const route = useRoute();

onMounted(() => {
  const selector = route.query.selector as string | undefined;
  if (selector) {
    try {
      localStorage.setItem(
        STORAGE_KEY,
        JSON.stringify({ selector, ts: Date.now() })
      );
    } catch {
      /* ignore */
    }
  }
  try {
    window.close();
  } catch {
    /* popup may not be closeable in some browsers */
  }
});
</script>

<template>
  <div class="min-h-screen flex items-center justify-center bg-background p-4">
    <p class="text-sm text-muted-foreground">
      Selector saved. You can close this window.
    </p>
  </div>
</template>
