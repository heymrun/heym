<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from "vue";
import { Copy, Download, Search, X } from "lucide-vue-next";
import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Input from "@/components/ui/Input.vue";
import Select from "@/components/ui/Select.vue";
import { logsApi } from "@/services/api";

const containerName = ref("heym-backend");
const logs = ref<string>("");
const loading = ref(false);
const error = ref<string | null>(null);
const searchQuery = ref("");
const autoScroll = ref(true);
const streaming = ref(false);
const streamStop = ref<(() => void) | null>(null);
const logLevel = ref<string>("all");
const logContainer = ref<HTMLDivElement | null>(null);

const containers = [
  { value: "all", label: "All Containers" },
  { value: "heym-backend", label: "Backend" },
  { value: "heym-frontend", label: "Frontend" },
  { value: "heym-postgres", label: "PostgreSQL" },
];

const logLevels = [
  { value: "all", label: "All" },
  { value: "INFO", label: "INFO" },
  { value: "WARNING", label: "WARNING" },
  { value: "ERROR", label: "ERROR" },
  { value: "DEBUG", label: "DEBUG" },
];

const filteredLogs = computed(() => {
  let filtered = logs.value;

  if (logLevel.value !== "all") {
    filtered = filtered
      .split("\n")
      .filter((line) => line.includes(logLevel.value))
      .join("\n");
  }

  if (searchQuery.value) {
    const query = searchQuery.value.toLowerCase();
    filtered = filtered
      .split("\n")
      .filter((line) => line.toLowerCase().includes(query))
      .join("\n");
  }

  return filtered;
});

async function loadLogs(): Promise<void> {
  try {
    loading.value = true;
    error.value = null;
    if (containerName.value === "all") {
      const allLogs: string[] = [];
      const containerNames = ["heym-backend", "heym-frontend", "heym-postgres"];
      for (const name of containerNames) {
        try {
          const logData = await logsApi.getDockerLogs(name, 500);
          allLogs.push(`\n=== ${name.toUpperCase()} ===\n${logData}`);
        } catch (err) {
          allLogs.push(`\n=== ${name.toUpperCase()} ===\nError loading logs: ${err instanceof Error ? err.message : "Unknown error"}`);
        }
      }
      logs.value = allLogs.join("\n");
    } else {
      const logData = await logsApi.getDockerLogs(containerName.value, 500);
      logs.value = logData;
    }
    if (autoScroll.value) {
      nextTick(() => scrollToBottom());
    }
  } catch (err) {
    error.value = err instanceof Error ? err.message : "Failed to load logs";
  } finally {
    loading.value = false;
  }
}

function startStreaming(): void {
  if (streaming.value) {
    stopStreaming();
    return;
  }

  if (containerName.value === "all") {
    error.value = "Cannot stream logs from all containers. Please select a specific container.";
    return;
  }

  streaming.value = true;
  error.value = null;

  streamStop.value = logsApi.streamDockerLogs(
    containerName.value,
    (logLine) => {
      logs.value += logLine;
      if (autoScroll.value) {
        nextTick(() => scrollToBottom());
      }
    },
    (err) => {
      error.value = err.message;
      streaming.value = false;
    },
  );
}

function stopStreaming(): void {
  if (streamStop.value) {
    streamStop.value();
    streamStop.value = null;
  }
  streaming.value = false;
}

function scrollToBottom(): void {
  if (logContainer.value) {
    logContainer.value.scrollTop = logContainer.value.scrollHeight;
  }
}

function copyLogs(): void {
  navigator.clipboard.writeText(filteredLogs.value);
}

function downloadLogs(): void {
  const blob = new Blob([filteredLogs.value], { type: "text/plain" });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `${containerName.value}-logs-${new Date().toISOString()}.txt`;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

watch(containerName, () => {
  stopStreaming();
  loadLogs();
});

watch(autoScroll, (enabled) => {
  if (enabled) {
    nextTick(() => scrollToBottom());
  }
});

onMounted(() => {
  loadLogs();
});

onUnmounted(() => {
  stopStreaming();
});
</script>

<template>
  <div class="flex h-full flex-col space-y-4 overflow-x-hidden max-w-full">
    <div class="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-3">
      <h2 class="text-2xl font-bold">
        Docker Logs
      </h2>
      <div class="flex items-center gap-2 flex-wrap">
        <Button
          :variant="streaming ? 'destructive' : 'default'"
          size="sm"
          class="text-xs sm:text-sm"
          :disabled="containerName === 'all'"
          @click="startStreaming"
        >
          <span class="hidden sm:inline">{{ streaming ? "Stop Streaming" : "Start Streaming" }}</span>
          <span class="sm:hidden">{{ streaming ? "Stop" : "Start" }}</span>
        </Button>
        <Button
          variant="outline"
          size="sm"
          :disabled="loading"
          @click="loadLogs"
        >
          Refresh
        </Button>
      </div>
    </div>

    <div class="flex flex-col gap-4">
      <div class="flex flex-col sm:flex-row items-stretch sm:items-center gap-3">
        <Select
          v-model="containerName"
          :options="containers"
          placeholder="Select container"
          class="w-full sm:w-48 flex-1 sm:flex-none"
        />
        <Select
          v-model="logLevel"
          :options="logLevels"
          placeholder="Type"
          class="w-full sm:w-40 flex-1 sm:flex-none"
        />
        <div class="flex items-center gap-2">
          <label class="flex items-center gap-2 text-sm">
            <input
              v-model="autoScroll"
              type="checkbox"
              class="rounded border-input"
            >
            Auto-scroll
          </label>
        </div>
      </div>
      <div class="relative">
        <Search class="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
        <Input
          v-model="searchQuery"
          placeholder="Filter logs... (type to filter log content)"
          class="pl-10"
        />
        <Button
          v-if="searchQuery"
          variant="ghost"
          size="icon"
          class="absolute right-1 top-1/2 h-9 w-9 md:h-7 md:w-7 -translate-y-1/2"
          @click="searchQuery = ''"
        >
          <X class="h-4 w-4" />
        </Button>
      </div>
      <div
        v-if="searchQuery || logLevel !== 'all'"
        class="text-sm text-muted-foreground"
      >
        <span v-if="searchQuery">
          Filtering by: "<span class="font-medium text-foreground">{{ searchQuery }}</span>"
        </span>
        <span v-if="logLevel !== 'all'">
          <span v-if="searchQuery"> | </span>
          Log level: <span class="font-medium text-foreground">{{ logLevel }}</span>
        </span>
        <span
          v-if="filteredLogs"
          class="ml-2"
        >
          ({{ filteredLogs.split('\n').filter(l => l.trim()).length }} lines)
        </span>
      </div>
    </div>

    <div
      v-if="error"
      class="rounded-lg bg-destructive/10 p-4 text-destructive"
    >
      {{ error }}
    </div>

    <Card class="relative flex flex-1 flex-col overflow-hidden overflow-x-hidden">
      <div class="absolute right-4 top-4 z-10 flex gap-2">
        <Button
          variant="ghost"
          size="icon"
          class="min-h-[44px] min-w-[44px] md:h-10 md:w-10"
          title="Copy logs"
          @click="copyLogs"
        >
          <Copy class="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          class="min-h-[44px] min-w-[44px] md:h-10 md:w-10"
          title="Download logs"
          @click="downloadLogs"
        >
          <Download class="h-4 w-4" />
        </Button>
      </div>
      <div
        ref="logContainer"
        class="flex-1 overflow-auto overflow-x-hidden bg-background p-4 font-mono text-sm"
        style="white-space: pre-wrap; word-break: break-all;"
      >
        <div
          v-if="loading && !logs"
          class="text-muted-foreground"
        >
          Loading logs...
        </div>
        <div
          v-else-if="filteredLogs"
          class="text-foreground"
        >
          {{ filteredLogs }}
        </div>
        <div
          v-else
          class="text-muted-foreground"
        >
          No logs available
        </div>
      </div>
    </Card>
  </div>
</template>
