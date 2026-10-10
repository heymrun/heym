import { createClarifyDataTables, type ClarifyDataTables } from "@/composables/clarifyDataTables";
import { dataTablesApi } from "@/services/api";

export { selectedTableOption, type ClarifyDataTables } from "@/composables/clarifyDataTables";

/** Data table state for one question card, over Heym's data tables API. */
export function useClarifyDataTables(): ClarifyDataTables {
  return createClarifyDataTables(dataTablesApi);
}
