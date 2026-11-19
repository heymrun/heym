import type { CreateGlobalVariableRequest, GlobalVariableValue } from "@/types/globalVariable";

/**
 * The body the variable dialog saves. The chosen type goes as it is, "auto" included: the
 * server reads "auto" as "infer the type from the value", while a missing type on an edit
 * means "keep the old type" and would coerce a list into a number variable.
 */
export function globalVariableSavePayload(
  name: string,
  value: GlobalVariableValue,
  valueType: string,
): CreateGlobalVariableRequest {
  return { name: name.trim(), value, value_type: valueType };
}
