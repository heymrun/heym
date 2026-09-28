import type { CredentialType } from "@/types/credential";
import type { DataTable, DataTableColumn } from "@/types/dataTable";

export type ClarifyQuestionType = "single" | "multi" | "text";

// A credential by type and name: the suggestion for a new one, or the one the form saved.
export interface ClarifyCredentialRef {
  type: CredentialType;
  name: string;
}

// An existing credential the form opens for editing.
export interface ClarifyCredentialEdit {
  id: string;
}

// An existing Heym data table a `table` option picks.
export interface ClarifyTableRef {
  id: string;
}

// A column of the table a `createTable` option proposes.
export interface ClarifyTableColumn {
  name: string;
  type: DataTableColumn["type"];
  required?: boolean;
  unique?: boolean;
}

// The new table a `createTable` option proposes; the card creates it on submit.
export interface ClarifyTableDraft {
  name: string;
  description?: string;
  columns: ClarifyTableColumn[];
}

// The data table an answer settled on: picked, or created by the card.
export interface ClarifyDataTableRef {
  id: string;
  name: string;
}

// A `table` option's table: undefined while it loads, null when it is not available.
export type ClarifyTableState = DataTable | null | undefined;

export interface ClarifyOption {
  label: string;
  // Editable value shown once this option is picked; single-choice questions only.
  prefill?: string;
  // Opens the credential dialog preset to this type and name; single-choice questions only.
  create?: ClarifyCredentialRef;
  // Opens the credential dialog on this credential; single-choice questions only.
  edit?: ClarifyCredentialEdit;
  // Picks an existing data table; single-choice questions only.
  table?: ClarifyTableRef;
  // Proposes a new data table the card creates on submit; single-choice questions only.
  createTable?: ClarifyTableDraft;
}

export interface ClarifyQuestion {
  id: string;
  text: string;
  type: ClarifyQuestionType;
  options?: ClarifyOption[];
  allowOther?: boolean;
  // Names the prefill input, e.g. "Header".
  prefillLabel?: string;
  // The workflow can be built without an answer.
  optional?: boolean;
}

export interface ClarifyPayload {
  questions: ClarifyQuestion[];
}

export interface ClarifyAnswer {
  id: string;
  text: string;
  // For single/multi: the chosen option label(s). For text: empty.
  selected: string[];
  // Free-text entered via "Other" or a text question.
  other: string;
  // The user's edit of the chosen option's prefill.
  prefill?: string;
  // The credential a `create` or `edit` option saved.
  credential?: ClarifyCredentialRef;
  // The data table a `table` or `createTable` option settled on.
  dataTable?: ClarifyDataTableRef;
}
