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
