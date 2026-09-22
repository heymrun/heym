export interface ModelRouterOptionForm {
  id: string;
  label: string;
  credentialId: string;
  model: string;
  criteria: string;
  isDefault: boolean;
}

export interface ModelRouterForm {
  decisionCredentialId: string;
  decisionModel: string;
  routingInstructions: string;
  options: ModelRouterOptionForm[];
}

export interface ModelRouterOptionConfig {
  id: string;
  label: string;
  credential_id: string;
  model: string;
  criteria: string;
  is_default: boolean;
}

export interface ModelRouterConfig {
  decision_credential_id: string;
  decision_model: string;
  routing_instructions: string;
  options: ModelRouterOptionConfig[];
}

export const DEFAULT_ROUTING_INSTRUCTIONS =
  "Choose the model best suited to this request. Read each option's criteria and pick the one whose criteria the request matches. When several fit, prefer the cheaper option.";

let optionCounter = 0;

export function createEmptyOption(): ModelRouterOptionForm {
  optionCounter += 1;
  return {
    id: `opt_${Date.now()}_${optionCounter}`,
    label: "",
    credentialId: "",
    model: "",
    criteria: "",
    isDefault: false,
  };
}

export function emptyModelRouterForm(): ModelRouterForm {
  return {
    decisionCredentialId: "",
    decisionModel: "",
    routingInstructions: DEFAULT_ROUTING_INSTRUCTIONS,
    options: [createEmptyOption(), createEmptyOption()],
  };
}

/** Mirrors `parse_router_config` on the backend so the dialog fails before the request. */
export function validateModelRouterForm(form: ModelRouterForm): string | null {
  if (!form.decisionCredentialId.trim()) return "Pick a decision model credential.";
  if (!form.decisionModel.trim()) return "Enter the decision model to use.";
  if (form.options.length < 2) {
    return "Add at least two model options; with one there is nothing to route.";
  }

  const seen = new Set<string>();
  for (const option of form.options) {
    const label = option.label.trim();
    if (!label) return "Every model option needs a name.";
    const lowered = label.toLowerCase();
    if (seen.has(lowered)) {
      return `Two model options share the same name "${label}". Names are what the decision model picks between.`;
    }
    seen.add(lowered);
    if (!option.credentialId.trim()) return `Model option "${label}" needs a credential.`;
    if (!option.model.trim()) return `Model option "${label}" needs a model.`;
  }

  if (form.options.filter((option) => option.isDefault).length > 1) {
    return "Only one option can be the fallback used when routing fails.";
  }
  return null;
}

export function buildModelRouterConfig(form: ModelRouterForm): ModelRouterConfig {
  return {
    decision_credential_id: form.decisionCredentialId.trim(),
    decision_model: form.decisionModel.trim(),
    routing_instructions: form.routingInstructions.trim(),
    options: form.options.map((option) => ({
      id: option.id,
      label: option.label.trim(),
      credential_id: option.credentialId.trim(),
      model: option.model.trim(),
      criteria: option.criteria.trim(),
      is_default: option.isDefault,
    })),
  };
}

/** Turn the stored config (from `GET /credentials/{id}/model-router`) back into a form. */
export function formFromModelRouterConfig(config: ModelRouterConfig): ModelRouterForm {
  return {
    decisionCredentialId: config.decision_credential_id,
    decisionModel: config.decision_model,
    routingInstructions: config.routing_instructions || DEFAULT_ROUTING_INSTRUCTIONS,
    options: config.options.map((option) => ({
      id: option.id,
      label: option.label,
      credentialId: option.credential_id,
      model: option.model,
      criteria: option.criteria,
      isDefault: option.is_default,
    })),
  };
}
