import { reactive, ref, type Ref } from "vue";
import axios from "axios";

import type {
  ClarifyAnswer,
  ClarifyDataTableRef,
  ClarifyOption,
  ClarifyQuestion,
  ClarifyTableDraft,
  ClarifyTableState,
} from "@/types/clarify";
import type { DataTable, DataTableColumn } from "@/types/dataTable";

import { dataTablesApi } from "@/services/api";

export interface ClarifyDataTables {
  // True while Submit creates tables.
  creating: Ref<boolean>;
  // A create failure per question id, shown under that question.
  errors: Record<string, string>;
  // The table a `table` option points at: undefined while it loads, null when unavailable.
  tableState: (option: ClarifyOption) => ClarifyTableState;
  // Clears the question's error and starts loading a picked table's columns.
  select: (question: ClarifyQuestion, option: ClarifyOption) => void;
  // Settles every selected table option before the answers go out; false when a create failed.
  prepare: (
    questions: ClarifyQuestion[],
    state: Record<string, ClarifyAnswer>,
    onCreated: (table: DataTable) => void,
  ) => Promise<boolean>;
}

/** The selected option of a single-choice question that picks or proposes a data table. */
export function selectedTableOption(
  question: ClarifyQuestion,
  answer: ClarifyAnswer,
): ClarifyOption | undefined {
  if (question.type !== "single") return undefined;
  return question.options?.find(
    (option) => (option.table || option.createTable) && answer.selected.includes(option.label),
  );
}

function draftColumns(draft: ClarifyTableDraft): DataTableColumn[] {
  return draft.columns.map((column, order) => ({
    id: crypto.randomUUID(),
    name: column.name,
    type: column.type,
    required: column.required ?? false,
    unique: column.unique ?? false,
    defaultValue: null,
    order,
  }));
}

function createErrorMessage(error: unknown): string {
  if (axios.isAxiosError(error)) {
    const detail: unknown = error.response?.data?.detail;
    if (typeof detail === "string" && detail.trim()) return detail;
  }
  return "The table could not be created.";
}

/** Data table state for one question card: picked tables it shows, tables it creates. */
export function useClarifyDataTables(): ClarifyDataTables {
  const creating = ref(false);
  const errors = reactive<Record<string, string>>({});
  const tables = reactive<Record<string, DataTable | null>>({});
  const loads = new Map<string, Promise<void>>();
  // Tables Submit already created, by question and option, so a retry never creates twice.
  const created = new Map<string, ClarifyDataTableRef>();

  function load(id: string): Promise<void> {
    const pending = loads.get(id);
    if (pending) return pending;
    const request = (async (): Promise<void> => {
      try {
        tables[id] = await dataTablesApi.get(id);
      } catch {
        tables[id] = null;
      }
    })();
    loads.set(id, request);
    return request;
  }

  function tableState(option: ClarifyOption): ClarifyTableState {
    return option.table ? tables[option.table.id] : undefined;
  }

  function select(question: ClarifyQuestion, option: ClarifyOption): void {
    delete errors[question.id];
    if (option.table) void load(option.table.id);
  }

  async function settle(
    question: ClarifyQuestion,
    option: ClarifyOption,
    answer: ClarifyAnswer,
    onCreated: (table: DataTable) => void,
  ): Promise<void> {
    if (option.table) {
      await load(option.table.id);
      const table = tables[option.table.id];
      if (table) answer.dataTable = { id: table.id, name: table.name };
      else delete answer.dataTable;
      return;
    }
    if (!option.createTable) return;
    const key = `${question.id}\u0000${option.label}`;
    const known = created.get(key);
    if (known) {
      answer.dataTable = known;
      return;
    }
    const table = await dataTablesApi.create({
      name: option.createTable.name,
      description: option.createTable.description,
      columns: draftColumns(option.createTable),
    });
    const settled = { id: table.id, name: table.name };
    created.set(key, settled);
    answer.dataTable = settled;
    onCreated(table);
  }

  async function prepare(
    questions: ClarifyQuestion[],
    state: Record<string, ClarifyAnswer>,
    onCreated: (table: DataTable) => void,
  ): Promise<boolean> {
    creating.value = true;
    try {
      for (const question of questions) {
        const answer = state[question.id];
        const option = answer ? selectedTableOption(question, answer) : undefined;
        if (!option) continue;
        try {
          await settle(question, option, answer, onCreated);
        } catch (error: unknown) {
          errors[question.id] = createErrorMessage(error);
          return false;
        }
      }
      return true;
    } finally {
      creating.value = false;
    }
  }

  return { creating, errors, tableState, select, prepare };
}
