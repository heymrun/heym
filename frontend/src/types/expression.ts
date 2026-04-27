export type SuggestionType =
  | "node"
  | "property"
  | "function"
  | "keyword"
  | "hint";

export type PropertyType =
  | "string"
  | "number"
  | "boolean"
  | "object"
  | "array"
  | "null"
  | "unknown";

export interface CompletionSuggestion {
  label: string;
  insertText: string;
  type: SuggestionType;
  detail?: string;
  description?: string;
  propertyType?: PropertyType;
  /** When set on a hint, ExpressionInput can show a Run control (e.g. populate node outputs). */
  hintAction?: "run-workflow";
}

export type TriggerKind = "node" | "property" | "function" | "none" | "item";

export interface CompletionContext {
  triggerKind: TriggerKind;
  nodeLabel?: string;
  propertyPath: string[];
  prefix: string;
  startOffset: number;
  endOffset: number;
  isInsideFilterExpr?: boolean;
  isInsideFunctionArg?: boolean;
}

export const ITEM_SUGGESTIONS: CompletionSuggestion[] = [
  {
    label: "item",
    insertText: "item",
    type: "keyword",
    detail: "Current element",
    description: "Reference current array element in filter/map/sort",
    propertyType: "unknown",
  },
];

export const ITEM_PROPERTIES: CompletionSuggestion[] = [
  {
    label: "length",
    insertText: "length",
    type: "property",
    detail: "String/array length",
    propertyType: "number",
  },
  {
    label: "upper",
    insertText: "upper()",
    type: "function",
    detail: "Convert to uppercase",
    propertyType: "string",
  },
  {
    label: "lower",
    insertText: "lower()",
    type: "function",
    detail: "Convert to lowercase",
    propertyType: "string",
  },
  {
    label: "strip",
    insertText: "strip()",
    type: "function",
    detail: "Remove whitespace",
    propertyType: "string",
  },
  {
    label: "contains",
    insertText: 'contains("")',
    type: "function",
    detail: "Check if contains substring",
    propertyType: "boolean",
  },
  {
    label: "startswith",
    insertText: 'startswith("")',
    type: "function",
    detail: "Check if starts with",
    propertyType: "boolean",
  },
  {
    label: "endswith",
    insertText: 'endswith("")',
    type: "function",
    detail: "Check if ends with",
    propertyType: "boolean",
  },
  {
    label: "split",
    insertText: 'split("")',
    type: "function",
    detail: "Split string into array",
    propertyType: "array",
  },
  {
    label: "replace",
    insertText: 'replace("", "")',
    type: "function",
    detail: "Replace substring",
    propertyType: "string",
  },
  {
    label: "substring",
    insertText: "substring(0, 5)",
    type: "function",
    detail: "Extract substring",
    propertyType: "string",
  },
  {
    label: "indexOf",
    insertText: 'indexOf("")',
    type: "function",
    detail: "Find index of substring",
    propertyType: "number",
  },
  {
    label: "toString",
    insertText: "toString()",
    type: "function",
    detail: "Convert to string",
    propertyType: "string",
  },
];

export const FILTER_CONTEXT_FUNCTIONS: CompletionSuggestion[] = [
  {
    label: "len(item)",
    insertText: "len(item)",
    type: "function",
    detail: "Get length of item",
    description: "Returns length of string or array",
    propertyType: "number",
  },
  {
    label: "str(item)",
    insertText: "str(item)",
    type: "function",
    detail: "Convert item to string",
    propertyType: "string",
  },
  {
    label: "int(item)",
    insertText: "int(item)",
    type: "function",
    detail: "Convert item to integer",
    propertyType: "number",
  },
  {
    label: "float(item)",
    insertText: "float(item)",
    type: "function",
    detail: "Convert item to float",
    propertyType: "number",
  },
  {
    label: "bool(item)",
    insertText: "bool(item)",
    type: "function",
    detail: "Convert item to boolean",
    propertyType: "boolean",
  },
];

export interface ExpressionTrigger {
  character: string;
  triggerKind: TriggerKind;
}

export const EXPRESSION_TRIGGERS: ExpressionTrigger[] = [
  { character: "$", triggerKind: "node" },
  { character: ".", triggerKind: "property" },
];

export const DATE_BUILTINS: CompletionSuggestion[] = [
  {
    label: "now",
    insertText: "now",
    type: "function",
    detail: "Current datetime",
    description: "Current date and time",
  },
  {
    label: "Date",
    insertText: 'Date("")',
    type: "function",
    detail: "Parse/create date",
    description: 'Date("2024-01-15") or Date()',
  },
  {
    label: "UUID",
    insertText: "UUID",
    type: "function",
    detail: "Generate unique ID",
    description: "32-character unique identifier",
  },
];

export const DATE_METHODS: CompletionSuggestion[] = [
  {
    label: "format",
    insertText: 'format("YYYY-MM-DD")',
    type: "function",
    detail: "Format date",
    description: 'format("YYYY-MM-DD HH:mm:ss")',
    propertyType: "string",
  },
  {
    label: "toISO",
    insertText: "toISO()",
    type: "function",
    detail: "ISO 8601 format",
    description: "2024-01-15T10:30:00.000Z",
    propertyType: "string",
  },
  {
    label: "toDate",
    insertText: "toDate()",
    type: "function",
    detail: "Date only",
    description: "YYYY-MM-DD",
    propertyType: "string",
  },
  {
    label: "toTime",
    insertText: "toTime()",
    type: "function",
    detail: "Time only",
    description: "HH:mm:ss",
    propertyType: "string",
  },
  {
    label: "toUnix",
    insertText: "toUnix()",
    type: "function",
    detail: "Unix timestamp",
    description: "Seconds since epoch",
    propertyType: "number",
  },
  {
    label: "toMillis",
    insertText: "toMillis()",
    type: "function",
    detail: "Milliseconds timestamp",
    description: "Milliseconds since epoch",
    propertyType: "number",
  },
  {
    label: "year",
    insertText: "year",
    type: "property",
    detail: "Year (4 digits)",
    propertyType: "number",
  },
  {
    label: "month",
    insertText: "month",
    type: "property",
    detail: "Month (1-12)",
    propertyType: "number",
  },
  {
    label: "day",
    insertText: "day",
    type: "property",
    detail: "Day of month (1-31)",
    propertyType: "number",
  },
  {
    label: "hour",
    insertText: "hour",
    type: "property",
    detail: "Hour (0-23)",
    propertyType: "number",
  },
  {
    label: "minute",
    insertText: "minute",
    type: "property",
    detail: "Minute (0-59)",
    propertyType: "number",
  },
  {
    label: "second",
    insertText: "second",
    type: "property",
    detail: "Second (0-59)",
    propertyType: "number",
  },
  {
    label: "dayOfWeek",
    insertText: "dayOfWeek",
    type: "property",
    detail: "Day of week (0-6, Sun=0)",
    propertyType: "number",
  },
  {
    label: "addDays",
    insertText: "addDays(1)",
    type: "function",
    detail: "Add days",
    description: "addDays(n)",
    propertyType: "object",
  },
  {
    label: "addHours",
    insertText: "addHours(1)",
    type: "function",
    detail: "Add hours",
    description: "addHours(n)",
    propertyType: "object",
  },
  {
    label: "addMinutes",
    insertText: "addMinutes(1)",
    type: "function",
    detail: "Add minutes",
    description: "addMinutes(n)",
    propertyType: "object",
  },
  {
    label: "addMonths",
    insertText: "addMonths(1)",
    type: "function",
    detail: "Add months",
    description: "addMonths(n)",
    propertyType: "object",
  },
  {
    label: "addYears",
    insertText: "addYears(1)",
    type: "function",
    detail: "Add years",
    description: "addYears(n)",
    propertyType: "object",
  },
  {
    label: "startOfDay",
    insertText: "startOfDay()",
    type: "function",
    detail: "Start of day (00:00:00)",
    propertyType: "object",
  },
  {
    label: "endOfDay",
    insertText: "endOfDay()",
    type: "function",
    detail: "End of day (23:59:59)",
    propertyType: "object",
  },
  {
    label: "startOfMonth",
    insertText: "startOfMonth()",
    type: "function",
    detail: "First day of month",
    propertyType: "object",
  },
  {
    label: "endOfMonth",
    insertText: "endOfMonth()",
    type: "function",
    detail: "Last day of month",
    propertyType: "object",
  },
  {
    label: "toString",
    insertText: "toString()",
    type: "function",
    detail: "Convert to ISO string",
    propertyType: "string",
  },
];

export const BUILTIN_FUNCTIONS: CompletionSuggestion[] = [
  {
    label: "str",
    insertText: "str()",
    type: "function",
    detail: "Convert to string",
    description: "str($value)",
  },
  {
    label: "int",
    insertText: "int()",
    type: "function",
    detail: "Convert to integer",
    description: "int($value)",
  },
  {
    label: "float",
    insertText: "float()",
    type: "function",
    detail: "Convert to float",
    description: "float($value)",
  },
  {
    label: "bool",
    insertText: "bool()",
    type: "function",
    detail: "Convert to boolean",
    description: "bool($value)",
  },
  {
    label: "list",
    insertText: "list()",
    type: "function",
    detail: "Convert to list",
    description: "list($value)",
  },
  {
    label: "dict",
    insertText: "dict(key=value)",
    type: "function",
    detail: "Create dictionary (simple keys)",
    description: 'dict(name="Ali", age=30)',
  },
  {
    label: "object",
    insertText: '{"key": "value"}',
    type: "function",
    detail: "Create object literal (any keys)",
    description: '${"January 23": "Ali", "name": "value"}',
  },
  {
    label: "len",
    insertText: "len()",
    type: "function",
    detail: "Get length",
    description: "len($value)",
  },
  {
    label: "abs",
    insertText: "abs()",
    type: "function",
    detail: "Absolute value",
    description: "abs($number)",
  },
  {
    label: "min",
    insertText: "min()",
    type: "function",
    detail: "Minimum value",
    description: "min($a, $b)",
  },
  {
    label: "max",
    insertText: "max()",
    type: "function",
    detail: "Maximum value",
    description: "max($a, $b)",
  },
  {
    label: "round",
    insertText: "round()",
    type: "function",
    detail: "Round number",
    description: "round($number)",
  },
  {
    label: "sum",
    insertText: "sum()",
    type: "function",
    detail: "Sum of list",
    description: "sum($list)",
  },
  {
    label: "sorted",
    insertText: "sorted()",
    type: "function",
    detail: "Sort list",
    description: "sorted($list)",
  },
  {
    label: "upper",
    insertText: "upper()",
    type: "function",
    detail: "Uppercase",
    description: "upper($text)",
  },
  {
    label: "lower",
    insertText: "lower()",
    type: "function",
    detail: "Lowercase",
    description: "lower($text)",
  },
  {
    label: "strip",
    insertText: "strip()",
    type: "function",
    detail: "Trim whitespace",
    description: "strip($text)",
  },
  {
    label: "capitalize",
    insertText: "capitalize()",
    type: "function",
    detail: "Capitalize first",
    description: "capitalize($text)",
  },
  {
    label: "title",
    insertText: "title()",
    type: "function",
    detail: "Title case",
    description: "title($text)",
  },
  {
    label: "split",
    insertText: "split()",
    type: "function",
    detail: "Split string",
    description: 'split($text, ",")',
  },
  {
    label: "join",
    insertText: "join()",
    type: "function",
    detail: "Join list",
    description: 'join(", ", $list)',
  },
  {
    label: "replace",
    insertText: "replace()",
    type: "function",
    detail: "Replace text",
    description: 'replace($text, "old", "new")',
  },
  {
    label: "randomInt",
    insertText: "randomInt(0, 100)",
    type: "function",
    detail: "Random integer",
    description: "randomInt(min, max)",
  },
  {
    label: "range",
    insertText: "range(0, 10)",
    type: "function",
    detail: "Integer range (b excluded)",
    description: "range(a, b) -> [a, ..., b-1]",
  },
  {
    label: "array",
    insertText: "array()",
    type: "function",
    detail: "Create array",
    description: 'array(1, 2, 3) or array("a", "b")',
  },
  {
    label: "notNull",
    insertText: "notNull()",
    type: "function",
    detail: "Remove null values from array",
    description: "notNull($list)",
  },
];

export const STRING_METHODS: CompletionSuggestion[] = [
  {
    label: "upper",
    insertText: "upper()",
    type: "function",
    detail: "Uppercase",
    propertyType: "string",
  },
  {
    label: "lower",
    insertText: "lower()",
    type: "function",
    detail: "Lowercase",
    propertyType: "string",
  },
  {
    label: "strip",
    insertText: "strip()",
    type: "function",
    detail: "Trim whitespace",
    propertyType: "string",
  },
  {
    label: "capitalize",
    insertText: "capitalize()",
    type: "function",
    detail: "Capitalize first",
    propertyType: "string",
  },
  {
    label: "title",
    insertText: "title()",
    type: "function",
    detail: "Title case",
    propertyType: "string",
  },
  {
    label: "charAt",
    insertText: "charAt()",
    type: "function",
    detail: "Get char at index",
    propertyType: "string",
  },
  {
    label: "replace",
    insertText: 'replace("", "")',
    type: "function",
    detail: "Replace text",
    propertyType: "string",
  },
  {
    label: "replaceAll",
    insertText: 'replaceAll("", "")',
    type: "function",
    detail: "Replace all occurrences",
    propertyType: "string",
  },
  {
    label: "regexReplace",
    insertText: 'regexReplace("", "")',
    type: "function",
    detail: "Replace with regex pattern",
    propertyType: "string",
  },
  {
    label: "substring",
    insertText: "substring(0)",
    type: "function",
    detail: "Slice by start/end index",
    propertyType: "string",
  },
  {
    label: "substr",
    insertText: "substr(0)",
    type: "function",
    detail: "Slice by start + length",
    propertyType: "string",
  },
  {
    label: "startswith",
    insertText: 'startswith("")',
    type: "function",
    detail: "Check if starts with",
    propertyType: "boolean",
  },
  {
    label: "endswith",
    insertText: 'endswith("")',
    type: "function",
    detail: "Check if ends with",
    propertyType: "boolean",
  },
  {
    label: "contains",
    insertText: 'contains("")',
    type: "function",
    detail: "Check if contains",
    propertyType: "boolean",
  },
  {
    label: "indexOf",
    insertText: 'indexOf("")',
    type: "function",
    detail: "Find index of substring",
    propertyType: "number",
  },
  {
    label: "reverse",
    insertText: "reverse()",
    type: "function",
    detail: "Reverse string",
    propertyType: "string",
  },
  {
    label: "split",
    insertText: 'split("")',
    type: "function",
    detail: "Split string into array",
    propertyType: "array",
  },
  {
    label: "hash",
    insertText: "hash()",
    type: "function",
    detail: "MD5 hash",
    propertyType: "string",
  },
  {
    label: "urlEncode",
    insertText: "urlEncode()",
    type: "function",
    detail: "URL encode string",
    propertyType: "string",
  },
  {
    label: "urlDecode",
    insertText: "urlDecode()",
    type: "function",
    detail: "URL decode string",
    propertyType: "string",
  },
  {
    label: "escape",
    insertText: "escape()",
    type: "function",
    detail: "JSON escape string",
    propertyType: "string",
  },
  {
    label: "unescape",
    insertText: "unescape()",
    type: "function",
    detail: "JSON unescape string",
    propertyType: "string",
  },
  {
    label: "length",
    insertText: "length",
    type: "property",
    detail: "Length (number)",
    propertyType: "number",
  },
];

export const ARRAY_METHODS: CompletionSuggestion[] = [
  {
    label: "flat",
    insertText: "flat()",
    type: "function",
    detail: "Flatten nested arrays",
    description: "Merge nested arrays into a single flat array",
    propertyType: "array",
  },
  {
    label: "reverse",
    insertText: "reverse()",
    type: "function",
    detail: "Reverse array",
    propertyType: "array",
  },
  {
    label: "first",
    insertText: "first()",
    type: "function",
    detail: "Get first element",
    propertyType: "unknown",
  },
  {
    label: "last",
    insertText: "last()",
    type: "function",
    detail: "Get last element",
    propertyType: "unknown",
  },
  {
    label: "random",
    insertText: "random()",
    type: "function",
    detail: "Get random element",
    propertyType: "unknown",
  },
  {
    label: "distinct",
    insertText: "distinct()",
    type: "function",
    detail: "Remove duplicate elements",
    propertyType: "array",
  },
  {
    label: "distinctBy",
    insertText: 'distinctBy("")',
    type: "function",
    detail: "Remove duplicates by property",
    description: '$array.distinctBy("item.id") - Keep first occurrence of each unique value',
    propertyType: "array",
  },
  {
    label: "notNull",
    insertText: "notNull()",
    type: "function",
    detail: "Remove null values",
    propertyType: "array",
  },
  {
    label: "filter",
    insertText: 'filter("")',
    type: "function",
    detail: "Filter array by condition",
    description: '$array.filter("item > 5") or $array.filter("item.active == true")',
    propertyType: "array",
  },
  {
    label: "map",
    insertText: 'map("")',
    type: "function",
    detail: "Transform each element",
    description: '$array.map("item.name") or $array.map("item * 2")',
    propertyType: "array",
  },
  {
    label: "sort",
    insertText: 'sort("")',
    type: "function",
    detail: "Sort array by expression",
    description: '$array.sort("item.age") or $array.sort("item", "desc")',
    propertyType: "array",
  },
  {
    label: "add",
    insertText: "add()",
    type: "function",
    detail: "Append item to array",
    propertyType: "array",
  },
  {
    label: "contains",
    insertText: "contains()",
    type: "function",
    detail: "Check if array contains item",
    propertyType: "boolean",
  },
  {
    label: "join",
    insertText: 'join(",")',
    type: "function",
    detail: "Join elements with separator",
    propertyType: "string",
  },
  {
    label: "take",
    insertText: "take()",
    type: "function",
    detail: "Take first/last N elements",
    description: "$array.take(2) for first 2, $array.take(-2) for last 2",
    propertyType: "array",
  },
  {
    label: "length",
    insertText: "length",
    type: "property",
    detail: "Length (number)",
    propertyType: "number",
  },
  {
    label: "toString",
    insertText: "toString()",
    type: "function",
    detail: "Convert to string",
    propertyType: "string",
  },
];

export const NUMBER_METHODS: CompletionSuggestion[] = [
  {
    label: "toString",
    insertText: "toString()",
    type: "function",
    detail: "Convert to string",
    propertyType: "string",
  },
];

export const BOOLEAN_METHODS: CompletionSuggestion[] = [
  {
    label: "toString",
    insertText: "toString()",
    type: "function",
    detail: "Convert to string",
    propertyType: "string",
  },
];

export const OBJECT_METHODS: CompletionSuggestion[] = [
  {
    label: "get",
    insertText: 'get("")',
    type: "function",
    detail: "Get value by key",
    description: 'get("key") or get("key", defaultValue)',
    propertyType: "unknown",
  },
  {
    label: "keys",
    insertText: "keys()",
    type: "function",
    detail: "List of keys",
    description: "Return all keys as an array",
    propertyType: "array",
  },
  {
    label: "values",
    insertText: "values()",
    type: "function",
    detail: "List of values",
    description: "Return all values as an array",
    propertyType: "array",
  },
  {
    label: "entries",
    insertText: "entries()",
    type: "function",
    detail: "List of {key, value} pairs",
    description: "Return an array of {key, value} entries",
    propertyType: "array",
  },
  {
    label: "filter",
    insertText: 'filter("item.value != null")',
    type: "function",
    detail: "Filter by entry expression",
    description: 'filter("expr") – iterates {key, value} entries; use item.key / item.value',
    propertyType: "array",
  },
  {
    label: "map",
    insertText: 'map("item.value")',
    type: "function",
    detail: "Map over entries",
    description: 'map("expr") – iterates {key, value} entries; use item.key / item.value',
    propertyType: "array",
  },
  {
    label: "toString",
    insertText: "toString()",
    type: "function",
    detail: "Convert to string",
    propertyType: "string",
  },
];
