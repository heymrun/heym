import type { NodeData } from "@/types/workflow";

/**
 * Decision fields are created and removed by the user, so their keys are built from
 * row positions rather than a fixed union: "state", "customBody", "img:0:source",
 * "q:0:instructions", "q:0:option:1", "q:2:level:0".
 */
export interface DecisionExpressionField {
  key: string;
  label: string;
}

/** Every expression-capable field a decision node shows, in panel order. */
export function getDecisionExpressionFields(data: NodeData): DecisionExpressionField[] {
  if (data.customBodyEnabled) {
    return [{ key: "customBody", label: "Request Body" }];
  }
  const fields: DecisionExpressionField[] = [{ key: "state", label: "State" }];
  if (data.imagesEnabled) {
    (data.images ?? []).forEach((image, index) => {
      const name = (image.name || "").trim() || `image ${index + 1}`;
      fields.push({ key: `img:${index}:source`, label: `${name} - image` });
    });
  }
  (data.questions ?? []).forEach((question, index) => {
    const name = (question.id || "").trim() || `question ${index + 1}`;
    fields.push({ key: `q:${index}:instructions`, label: `${name} - instructions` });
    if (question.type === "noul") {
      fields.push({ key: `q:${index}:criteriaTrue`, label: `${name} - yes means` });
      fields.push({ key: `q:${index}:criteriaFalse`, label: `${name} - no means` });
    } else if (question.type === "choice") {
      (question.options ?? []).forEach((option, optionIndex) => {
        const optionName = (option.key || "").trim() || `option ${optionIndex + 1}`;
        fields.push({
          key: `q:${index}:option:${optionIndex}`,
          label: `${name} - ${optionName}`,
        });
      });
    } else if (question.type === "score") {
      (question.levels ?? []).forEach((_level, levelIndex) => {
        fields.push({
          key: `q:${index}:level:${levelIndex}`,
          label: `${name} - level ${levelIndex}`,
        });
      });
    }
    // A box has instructions only.
  });
  return fields;
}
