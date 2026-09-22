import { describe, expect, it } from "vitest";

import {
  buildModelRouterConfig,
  createEmptyOption,
  emptyModelRouterForm,
  formFromModelRouterConfig,
  validateModelRouterForm,
  type ModelRouterForm,
} from "./modelRouterConfig";

function validForm(): ModelRouterForm {
  return {
    decisionCredentialId: "dec-1",
    decisionModel: "jev-latest",
    routingInstructions: "Pick the cheapest model that works.",
    options: [
      {
        id: "opt_1",
        label: "Fast",
        credentialId: "cred-1",
        model: "gpt-4o-mini",
        criteria: "Short questions.",
        isDefault: true,
      },
      {
        id: "opt_2",
        label: "Deep",
        credentialId: "cred-2",
        model: "gpt-5",
        criteria: "Hard questions.",
        isDefault: false,
      },
    ],
  };
}

describe("emptyModelRouterForm", () => {
  it("starts with two option rows so the shape is obvious", () => {
    const form = emptyModelRouterForm();
    expect(form.options).toHaveLength(2);
    expect(form.decisionCredentialId).toBe("");
    expect(form.routingInstructions.length).toBeGreaterThan(0);
  });
});

describe("createEmptyOption", () => {
  it("gives every row a distinct id", () => {
    expect(createEmptyOption().id).not.toBe(createEmptyOption().id);
  });
});

describe("validateModelRouterForm", () => {
  it("accepts a complete form", () => {
    expect(validateModelRouterForm(validForm())).toBeNull();
  });

  it("requires a decision credential", () => {
    const form = validForm();
    form.decisionCredentialId = "";
    expect(validateModelRouterForm(form)).toMatch(/decision model credential/i);
  });

  it("requires a decision model", () => {
    const form = validForm();
    form.decisionModel = "  ";
    expect(validateModelRouterForm(form)).toMatch(/decision model/i);
  });

  it("requires at least two options", () => {
    const form = validForm();
    form.options = form.options.slice(0, 1);
    expect(validateModelRouterForm(form)).toMatch(/two/i);
  });

  it("requires a name on every option", () => {
    const form = validForm();
    form.options[1].label = "";
    expect(validateModelRouterForm(form)).toMatch(/name/i);
  });

  it("rejects duplicate option names regardless of case", () => {
    const form = validForm();
    form.options[1].label = "fast";
    expect(validateModelRouterForm(form)).toMatch(/same name/i);
  });

  it("requires a credential and a model on every option", () => {
    const missingCredential = validForm();
    missingCredential.options[0].credentialId = "";
    expect(validateModelRouterForm(missingCredential)).toMatch(/credential/i);

    const missingModel = validForm();
    missingModel.options[1].model = "";
    expect(validateModelRouterForm(missingModel)).toMatch(/model/i);
  });

  it("allows zero defaults but not two", () => {
    const noDefault = validForm();
    noDefault.options[0].isDefault = false;
    expect(validateModelRouterForm(noDefault)).toBeNull();

    const twoDefaults = validForm();
    twoDefaults.options[1].isDefault = true;
    expect(validateModelRouterForm(twoDefaults)).toMatch(/one option/i);
  });
});

describe("buildModelRouterConfig", () => {
  it("emits the snake_case payload the API stores", () => {
    expect(buildModelRouterConfig(validForm())).toEqual({
      decision_credential_id: "dec-1",
      decision_model: "jev-latest",
      routing_instructions: "Pick the cheapest model that works.",
      options: [
        {
          id: "opt_1",
          label: "Fast",
          credential_id: "cred-1",
          model: "gpt-4o-mini",
          criteria: "Short questions.",
          is_default: true,
        },
        {
          id: "opt_2",
          label: "Deep",
          credential_id: "cred-2",
          model: "gpt-5",
          criteria: "Hard questions.",
          is_default: false,
        },
      ],
    });
  });

  it("trims every text field", () => {
    const form = validForm();
    form.decisionModel = "  jev-latest  ";
    form.options[0].label = "  Fast  ";
    const config = buildModelRouterConfig(form);
    expect(config.decision_model).toBe("jev-latest");
    expect(config.options[0].label).toBe("Fast");
  });
});

describe("formFromModelRouterConfig", () => {
  it("round-trips a stored config back into an editable form", () => {
    const form = validForm();
    expect(formFromModelRouterConfig(buildModelRouterConfig(form))).toEqual(form);
  });

  it("falls back to the default instructions when none were stored", () => {
    const config = buildModelRouterConfig(validForm());
    config.routing_instructions = "";
    expect(formFromModelRouterConfig(config).routingInstructions.length).toBeGreaterThan(0);
  });
});
