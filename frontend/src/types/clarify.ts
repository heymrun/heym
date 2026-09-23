export type ClarifyQuestionType = "single" | "multi" | "text";

export interface ClarifyOption {
  label: string;
  // Editable value shown once this option is picked; single-choice questions only.
  prefill?: string;
}

export interface ClarifyQuestion {
  id: string;
  text: string;
  type: ClarifyQuestionType;
  options?: ClarifyOption[];
  allowOther?: boolean;
  // Names the prefill input, e.g. "Header".
  prefillLabel?: string;
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
}
