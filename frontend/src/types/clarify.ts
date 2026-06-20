export type ClarifyQuestionType = "single" | "multi" | "text";

export interface ClarifyQuestion {
  id: string;
  text: string;
  type: ClarifyQuestionType;
  options?: string[];
  allowOther?: boolean;
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
}
