export interface DataTableColumn {
  id: string;
  name: string;
  type: "string" | "number" | "boolean" | "date" | "json";
  required: boolean;
  defaultValue: unknown;
  unique: boolean;
  order: number;
}

export interface DataTable {
  id: string;
  name: string;
  description: string | null;
  columns: DataTableColumn[];
  owner_id: string;
  row_count: number;
  created_at: string;
  updated_at: string;
}

export interface DataTableRow {
  id: string;
  table_id: string;
  data: Record<string, unknown>;
  created_by: string | null;
  updated_by: string | null;
  created_at: string;
  updated_at: string;
}

export interface DataTableListItem {
  id: string;
  name: string;
  description: string | null;
  column_count: number;
  row_count: number;
  owner_id: string;
  is_shared: boolean;
  shared_by: string | null;
  shared_by_team: string | null;
  permission: string | null;
  created_at: string;
  updated_at: string;
}

export interface DataTableShare {
  id: string;
  user_id: string;
  email: string;
  name: string;
  permission: string;
  shared_at: string;
}

export interface DataTableTeamShare {
  id: string;
  team_id: string;
  team_name: string;
  permission: string;
  shared_at: string;
}

export interface DataTableImportResult {
  imported: number;
  errors: Array<{ row: number; errors: string[] }>;
  total: number;
}
