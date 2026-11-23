export const heymBoardOperations = [
  {
    value: "getBoard",
    label: "Get Board",
    field: { key: "heymBoardId", label: "Board ID", placeholder: "$input.board_id" },
  },
  {
    value: "getBoardColumn",
    label: "Get Board Column",
    field: { key: "heymBoardColumnId", label: "Column ID", placeholder: "$input.column_id" },
  },
  {
    value: "getBoardCardId",
    label: "Get Board Card by ID",
    field: { key: "heymBoardCardId", label: "Card ID", placeholder: "$input.card_id" },
  },
] as const;

type HeymBoardOperation = (typeof heymBoardOperations)[number];
export type HeymBoardFieldKey = HeymBoardOperation["field"]["key"];

export function getHeymBoardOperation(value: string | undefined): HeymBoardOperation | undefined {
  return heymBoardOperations.find((operation) => operation.value === value);
}

/** The Heym operation that sends a message to Heym Chat instead of reading. */
export const HEYM_CHAT_OPERATION = "sendChatMessage";

export const heymChatOperationOption = {
  value: HEYM_CHAT_OPERATION,
  label: "Send Chat Message",
} as const;

export const HEYM_CHAT_FIELD_KEYS: readonly string[] = ["heymChatMessage", "heymChatConversationId"];

export type HeymChatFieldKey = "heymChatMessage" | "heymChatConversationId";

export interface HeymChatField {
  key: HeymChatFieldKey;
  label: string;
}

interface HeymChatToggles {
  heymChatContinue?: boolean;
}

export function isHeymChatOperation(operation: string | undefined): boolean {
  return operation === HEYM_CHAT_OPERATION;
}

/** The Heym node gets a QUESTION output, like Codex, only while it sends chat messages. */
export function hasHeymQuestionOutput(type: string, operation: string | undefined): boolean {
  return type === "heym" && isHeymChatOperation(operation);
}

/** Expression fields in panel order; the conversation id appears only while continuing. */
export function heymChatExpressionFields(data: HeymChatToggles): HeymChatField[] {
  const fields: HeymChatField[] = [{ key: "heymChatMessage", label: "Message" }];
  if (data.heymChatContinue === true) {
    fields.push({ key: "heymChatConversationId", label: "Conversation ID" });
  }
  return fields;
}
