<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { Coins, Plus, RefreshCcw, RotateCcw, Trash2, X } from "lucide-vue-next";

import type { LLMPricingRow, LLMPricingSyncStatus } from "@/types/pricing";

import Button from "@/components/ui/Button.vue";
import Card from "@/components/ui/Card.vue";
import Dialog from "@/components/ui/Dialog.vue";
import Input from "@/components/ui/Input.vue";
import Label from "@/components/ui/Label.vue";
import { formatDate } from "@/lib/utils";
import { llmPricingApi } from "@/services/api";

const rows = ref<LLMPricingRow[]>([]);
const syncStatus = ref<LLMPricingSyncStatus | null>(null);
const loading = ref(false);
const syncing = ref(false);
const error = ref("");
const search = ref("");

const editingId = ref<string | null>(null);
const editInput = ref({ input: "", output: "" });

const showAddDialog = ref(false);
const addForm = ref({ model: "", input: "", output: "" });
const adding = ref(false);
const addError = ref("");

const filteredRows = computed(() => {
  if (!search.value) return rows.value;
  const q = search.value.toLowerCase();
  return rows.value.filter(
    (r) =>
      r.model.toLowerCase().includes(q) || (r.provider ?? "").toLowerCase().includes(q),
  );
});

async function loadAll(): Promise<void> {
  loading.value = true;
  error.value = "";
  try {
    const [list, status] = await Promise.all([
      llmPricingApi.list(),
      llmPricingApi.syncStatus(),
    ]);
    rows.value = list;
    syncStatus.value = status;
  } catch {
    error.value = "Failed to load pricing";
  } finally {
    loading.value = false;
  }
}

async function refreshSync(): Promise<void> {
  syncing.value = true;
  try {
    await llmPricingApi.sync();
    for (let i = 0; i < 5; i++) {
      await new Promise<void>((r) => setTimeout(r, 800));
      const status = await llmPricingApi.syncStatus();
      if (status.last_synced_at !== syncStatus.value?.last_synced_at) {
        syncStatus.value = status;
        rows.value = await llmPricingApi.list();
        break;
      }
    }
  } finally {
    syncing.value = false;
  }
}

function startEdit(row: LLMPricingRow): void {
  editingId.value = row.id;
  editInput.value = {
    input: row.input_per_1m_usd,
    output: row.output_per_1m_usd,
  };
}

function cancelEdit(): void {
  editingId.value = null;
}

async function saveEdit(row: LLMPricingRow): Promise<void> {
  try {
    const updated = await llmPricingApi.updateOverride(row.model, {
      input_per_1m_usd: editInput.value.input,
      output_per_1m_usd: editInput.value.output,
    });
    const idx = rows.value.findIndex((r) => r.model === row.model);
    if (idx >= 0) rows.value[idx] = updated;
    editingId.value = null;
  } catch {
    error.value = `Failed to update ${row.model}`;
  }
}

async function resetOverride(row: LLMPricingRow): Promise<void> {
  if (!row.is_override) return;
  if (!confirm(`Reset pricing for ${row.model} to default?`)) return;
  try {
    await llmPricingApi.deleteOverride(row.model);
    await loadAll();
  } catch {
    error.value = `Failed to reset ${row.model}`;
  }
}

async function deleteCustom(row: LLMPricingRow): Promise<void> {
  if (!row.is_custom) return;
  if (!confirm(`Delete custom row ${row.model}?`)) return;
  try {
    await llmPricingApi.deleteOverride(row.model);
    await loadAll();
  } catch {
    error.value = `Failed to delete ${row.model}`;
  }
}

async function submitAdd(): Promise<void> {
  addError.value = "";
  if (!addForm.value.model || !addForm.value.input || !addForm.value.output) {
    addError.value = "All fields required";
    return;
  }
  adding.value = true;
  try {
    await llmPricingApi.createCustom({
      model: addForm.value.model,
      input_per_1m_usd: addForm.value.input,
      output_per_1m_usd: addForm.value.output,
    });
    showAddDialog.value = false;
    addForm.value = { model: "", input: "", output: "" };
    await loadAll();
  } catch (err) {
    addError.value =
      (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
      "Failed to add model";
  } finally {
    adding.value = false;
  }
}

function badgeFor(row: LLMPricingRow): { label: string; classes: string } | null {
  if (row.is_custom) return { label: "User added", classes: "bg-blue-500/15 text-blue-600" };
  if (row.is_override) return { label: "Customized", classes: "bg-amber-500/15 text-amber-600" };
  return null;
}

onMounted(() => {
  loadAll();
});
</script>

<template>
  <div class="space-y-4">
    <div class="flex flex-wrap items-center gap-2 justify-between">
      <div>
        <h2 class="text-xl font-semibold flex items-center gap-2">
          <Coins class="w-5 h-5" />
          LLM Cost Table
        </h2>
        <p class="text-xs text-muted-foreground">
          Per-model pricing used to compute cost in the Traces dashboard. Global rows are
          synced from Helicone; your edits create per-user overrides.
        </p>
      </div>
      <div class="flex items-center gap-2">
        <div class="text-xs text-muted-foreground">
          <span v-if="syncStatus?.last_synced_at">
            Last synced: {{ formatDate(syncStatus.last_synced_at) }}
          </span>
          <span v-else>Never synced</span>
        </div>
        <Button
          variant="outline"
          size="sm"
          :loading="syncing"
          @click="refreshSync"
        >
          <RefreshCcw class="w-4 h-4 mr-1" /> Refresh
        </Button>
        <Button
          variant="outline"
          size="sm"
          @click="showAddDialog = true"
        >
          <Plus class="w-4 h-4 mr-1" /> Add Custom Model
        </Button>
      </div>
    </div>

    <Input
      v-model="search"
      placeholder="Search model or provider…"
    />

    <div
      v-if="error"
      class="text-sm text-destructive"
    >
      {{ error }}
    </div>

    <Card
      variant="flat"
      :hover="false"
      class="p-0 overflow-hidden"
    >
      <table class="w-full text-sm">
        <thead class="bg-muted/30">
          <tr class="text-left text-xs uppercase tracking-wide text-muted-foreground">
            <th class="px-3 py-2">
              Provider
            </th>
            <th class="px-3 py-2">
              Model
            </th>
            <th class="px-3 py-2">
              Op
            </th>
            <th class="px-3 py-2">
              Input $/1M
            </th>
            <th class="px-3 py-2">
              Output $/1M
            </th>
            <th class="px-3 py-2">
              Source
            </th>
            <th class="px-3 py-2 text-right">
              Actions
            </th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="row in filteredRows"
            :key="row.id"
            class="border-t border-border/40"
          >
            <td class="px-3 py-2 text-xs text-muted-foreground">
              {{ row.provider ?? "—" }}
            </td>
            <td class="px-3 py-2 font-mono text-xs">
              {{ row.model }}
              <span
                v-if="badgeFor(row)"
                class="ml-2 text-[10px] px-1.5 py-0.5 rounded"
                :class="badgeFor(row)?.classes"
              >
                {{ badgeFor(row)?.label }}
              </span>
            </td>
            <td class="px-3 py-2 text-xs">
              {{ row.operator }}
            </td>
            <td class="px-3 py-2">
              <Input
                v-if="editingId === row.id"
                v-model="editInput.input"
                class="h-7 w-24"
              />
              <span v-else>${{ row.input_per_1m_usd }}</span>
            </td>
            <td class="px-3 py-2">
              <Input
                v-if="editingId === row.id"
                v-model="editInput.output"
                class="h-7 w-24"
              />
              <span v-else>${{ row.output_per_1m_usd }}</span>
            </td>
            <td class="px-3 py-2 text-xs text-muted-foreground">
              {{ row.source }}
            </td>
            <td class="px-3 py-2 text-right">
              <div class="flex items-center justify-end gap-1">
                <template v-if="editingId === row.id">
                  <Button
                    size="sm"
                    variant="outline"
                    @click="saveEdit(row)"
                  >
                    Save
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    @click="cancelEdit"
                  >
                    <X class="w-3 h-3" />
                  </Button>
                </template>
                <template v-else>
                  <Button
                    size="sm"
                    variant="ghost"
                    @click="startEdit(row)"
                  >
                    Edit
                  </Button>
                  <Button
                    v-if="row.is_override"
                    size="sm"
                    variant="ghost"
                    title="Reset to default"
                    @click="resetOverride(row)"
                  >
                    <RotateCcw class="w-3 h-3" />
                  </Button>
                  <Button
                    v-if="row.is_custom"
                    size="sm"
                    variant="ghost"
                    title="Delete"
                    @click="deleteCustom(row)"
                  >
                    <Trash2 class="w-3 h-3 text-destructive" />
                  </Button>
                </template>
              </div>
            </td>
          </tr>
          <tr v-if="filteredRows.length === 0">
            <td
              colspan="7"
              class="px-3 py-6 text-center text-sm text-muted-foreground"
            >
              {{ loading ? "Loading…" : "No pricing rows" }}
            </td>
          </tr>
        </tbody>
      </table>
    </Card>

    <Dialog
      :open="showAddDialog"
      title="Add Custom Model Pricing"
      size="md"
      @close="showAddDialog = false"
    >
      <div class="space-y-3">
        <div>
          <Label>Model name</Label>
          <Input
            v-model="addForm.model"
            placeholder="e.g. my-org/private-llm"
          />
        </div>
        <div class="grid grid-cols-2 gap-3">
          <div>
            <Label>Input $/1M</Label>
            <Input
              v-model="addForm.input"
              placeholder="0.50"
            />
          </div>
          <div>
            <Label>Output $/1M</Label>
            <Input
              v-model="addForm.output"
              placeholder="1.50"
            />
          </div>
        </div>
        <div
          v-if="addError"
          class="text-sm text-destructive"
        >
          {{ addError }}
        </div>
        <div class="flex justify-end gap-2">
          <Button
            variant="ghost"
            @click="showAddDialog = false"
          >
            Cancel
          </Button>
          <Button
            :loading="adding"
            @click="submitAdd"
          >
            Add
          </Button>
        </div>
      </div>
    </Dialog>
  </div>
</template>
