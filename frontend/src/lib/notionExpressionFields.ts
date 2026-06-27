export type NotionExpressionFieldKey =
  | "notionQuery"
  | "notionPageId"
  | "notionDatabaseId"
  | "notionDatabase"
  | "notionDataSourceId"
  | "notionDataSource"
  | "notionParentPageId"
  | "notionBlockId"
  | "notionBlock"
  | "notionProperties"
  | "notionIcon"
  | "notionCover"
  | "notionChildren"
  | "notionFilter"
  | "notionSort"
  | "notionSorts"
  | "notionStartCursor"
  | "notionAfterBlockId";

export interface NotionExpressionField {
  key: NotionExpressionFieldKey;
  label: string;
}

export interface NotionExpressionFieldContext {
  /** "select" | "expression" — data source field only renders as an expression input in expression mode. */
  dataSourceInputMode?: string;
  /** "select" | "expression" — parent page field only renders as an expression input in expression mode. */
  parentPageInputMode?: string;
  /** "end" | "after_block" — the After Block ID field only renders when appending after a block. */
  appendPosition?: string;
  /** Used to resolve the effective append position when it has not been set explicitly. */
  afterBlockId?: string;
}

/**
 * Returns the ordered expression-evaluate dialog slots for the given Notion operation.
 * The order mirrors the rendered order of the expression inputs in PropertiesPanel so the
 * single expand dialog can navigate (prev/next) across every input the operation exposes.
 * Only fields that currently render as expression inputs are included.
 */
export function getNotionExpressionFields(
  operation: string,
  context: NotionExpressionFieldContext = {},
): NotionExpressionField[] {
  const op = operation || "";
  const fields: NotionExpressionField[] = [];
  const dataSourceIsExpression =
    (context.dataSourceInputMode || "select") === "expression";
  const parentPageIsExpression =
    (context.parentPageInputMode || "select") === "expression";
  const appendPosition =
    context.appendPosition || (context.afterBlockId ? "after_block" : "end");

  const appendDataSource = (): void => {
    if (dataSourceIsExpression) {
      fields.push({ key: "notionDataSourceId", label: "Data Source" });
    }
  };

  switch (op) {
    case "search":
      fields.push({ key: "notionQuery", label: "Search Query" });
      fields.push({ key: "notionFilter", label: "Filter" });
      fields.push({ key: "notionSort", label: "Sort" });
      fields.push({ key: "notionStartCursor", label: "Start Cursor" });
      break;
    case "getPage":
    case "trashPage":
    case "restorePage":
      fields.push({ key: "notionPageId", label: "Page ID" });
      break;
    case "updatePage":
      fields.push({ key: "notionPageId", label: "Page ID" });
      fields.push({ key: "notionProperties", label: "Properties" });
      fields.push({ key: "notionIcon", label: "Icon" });
      fields.push({ key: "notionCover", label: "Cover" });
      break;
    case "retrieveDatabase":
      fields.push({ key: "notionDatabaseId", label: "Database ID" });
      break;
    case "updateDatabase":
      fields.push({ key: "notionDatabaseId", label: "Database ID" });
      fields.push({ key: "notionDatabase", label: "Database Request" });
      break;
    case "createDatabase":
      fields.push({ key: "notionDatabase", label: "Database Request" });
      break;
    case "createPage":
      appendDataSource();
      if (parentPageIsExpression) {
        fields.push({ key: "notionParentPageId", label: "Parent Page ID" });
      }
      fields.push({ key: "notionProperties", label: "Properties" });
      fields.push({ key: "notionIcon", label: "Icon" });
      fields.push({ key: "notionCover", label: "Cover" });
      fields.push({ key: "notionChildren", label: "Children" });
      break;
    case "retrieveDataSource":
      appendDataSource();
      break;
    case "updateDataSource":
      appendDataSource();
      fields.push({ key: "notionDataSource", label: "Data Source Request" });
      break;
    case "queryDataSource":
      appendDataSource();
      fields.push({ key: "notionFilter", label: "Filter" });
      fields.push({ key: "notionSorts", label: "Sorts" });
      fields.push({ key: "notionStartCursor", label: "Start Cursor" });
      break;
    case "createDataSource":
      fields.push({ key: "notionDataSource", label: "Data Source Request" });
      break;
    case "getBlockChildren":
      fields.push({ key: "notionBlockId", label: "Block ID" });
      fields.push({ key: "notionStartCursor", label: "Start Cursor" });
      break;
    case "updateBlock":
      fields.push({ key: "notionBlockId", label: "Block ID" });
      fields.push({ key: "notionBlock", label: "Block Update" });
      break;
    case "deleteBlock":
      fields.push({ key: "notionBlockId", label: "Block ID" });
      break;
    case "appendBlocks":
      fields.push({ key: "notionBlockId", label: "Block ID" });
      fields.push({ key: "notionChildren", label: "Children" });
      if (appendPosition === "after_block") {
        fields.push({ key: "notionAfterBlockId", label: "After Block ID" });
      }
      break;
    default:
      break;
  }

  return fields;
}
