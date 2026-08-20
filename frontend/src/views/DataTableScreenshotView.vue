<script setup lang="ts">
import { onBeforeMount } from "vue";

import DataTablePanel from "@/components/DataTable/DataTablePanel.vue";
import { dataTablesApi } from "@/services/api";
import type { DataTableListItem } from "@/types/dataTable";

const sampleTables: DataTableListItem[] = [
  {
    id: "dt-sample-customers",
    name: "Customers",
    description: "Customer contact records",
    column_count: 5,
    row_count: 42,
    owner_id: "user-1",
    is_shared: false,
    shared_by: null,
    shared_by_team: null,
    permission: "owner",
    created_at: "2026-08-18T09:00:00Z",
    updated_at: "2026-08-20T10:00:00Z",
  },
  {
    id: "dt-sample-orders",
    name: "Orders",
    description: "Order history",
    column_count: 8,
    row_count: 128,
    owner_id: "user-1",
    is_shared: true,
    shared_by: null,
    shared_by_team: "Engineering",
    permission: "write",
    created_at: "2026-08-15T12:30:00Z",
    updated_at: "2026-08-19T16:45:00Z",
  },
  {
    id: "dt-sample-products",
    name: "Products",
    description: null,
    column_count: 4,
    row_count: 15,
    owner_id: "user-1",
    is_shared: false,
    shared_by: null,
    shared_by_team: null,
    permission: "owner",
    created_at: "2026-08-20T08:00:00Z",
    updated_at: "2026-08-20T08:00:00Z",
  },
];

onBeforeMount(() => {
  dataTablesApi.list = async (): Promise<DataTableListItem[]> => sampleTables;
});
</script>

<template>
  <div class="h-screen bg-background p-6">
    <DataTablePanel />
  </div>
</template>
