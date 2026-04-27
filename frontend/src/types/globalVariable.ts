export type GlobalVariableValue =
  | string
  | number
  | boolean
  | unknown[]
  | Record<string, unknown>;

export interface GlobalVariable {
  id: string;
  name: string;
  value: GlobalVariableValue;
  value_type: string;
  created_at: string;
  updated_at: string;
}

export interface GlobalVariableListItem {
  id: string;
  name: string;
  value: GlobalVariableValue;
  value_type: string;
  created_at: string;
  updated_at: string;
  is_shared: boolean;
  shared_by: string | null;
}

export interface GlobalVariableShare {
  id: string;
  user_id: string;
  email: string;
  name: string;
  shared_at: string;
}

export interface CreateGlobalVariableRequest {
  name: string;
  value: GlobalVariableValue;
  value_type?: string;
}

export interface UpdateGlobalVariableRequest {
  name?: string;
  value?: GlobalVariableValue;
  value_type?: string;
}
