import { describe, expect, it } from "vitest";

import {
  buildJiraCredentialConfig,
  isJiraCredentialComplete,
  normalizeJiraAuthMode,
  type JiraCompletenessInput,
  type JiraCredentialForm,
} from "./jiraCredentialConfig";

function form(overrides: Partial<JiraCredentialForm> = {}): JiraCredentialForm {
  return {
    email: "ada@example.com",
    secret: "secret",
    baseUrl: "https://jira.corp.example.com",
    deployment: "data_center",
    apiVersion: "3",
    authMode: "basic",
    ...overrides,
  };
}

function completeness(overrides: Partial<JiraCompletenessInput> = {}): JiraCompletenessInput {
  return { ...form(), isEditing: false, ...overrides };
}

describe("normalizeJiraAuthMode", () => {
  it("treats a missing mode as basic so legacy credentials keep working", () => {
    expect(normalizeJiraAuthMode(undefined)).toBe("basic");
    expect(normalizeJiraAuthMode("")).toBe("basic");
    expect(normalizeJiraAuthMode("pat")).toBe("pat");
  });
});

describe("buildJiraCredentialConfig", () => {
  it("sends email, token and basic mode for Data Center basic auth", () => {
    expect(buildJiraCredentialConfig(form())).toEqual({
      email: "ada@example.com",
      api_token: "secret",
      base_url: "https://jira.corp.example.com",
      deployment: "data_center",
      auth_mode: "basic",
      api_version: "2",
    });
  });

  it("omits the email in PAT mode", () => {
    const config = buildJiraCredentialConfig(form({ authMode: "pat" }));
    expect(config.auth_mode).toBe("pat");
    expect(config).not.toHaveProperty("email");
    expect(config.api_token).toBe("secret");
  });

  it("never sends pat for Jira Cloud, even if the toggle was left on pat", () => {
    const config = buildJiraCredentialConfig(form({ deployment: "cloud", authMode: "pat" }));
    expect(config.auth_mode).toBe("basic");
    expect(config.email).toBe("ada@example.com");
    expect(config.api_version).toBe("3");
  });
});

describe("isJiraCredentialComplete", () => {
  it("needs no email in PAT mode", () => {
    expect(isJiraCredentialComplete(completeness({ authMode: "pat", email: "" }))).toBe(true);
  });

  it("still needs an email in basic mode", () => {
    expect(isJiraCredentialComplete(completeness({ email: "" }))).toBe(false);
  });

  it("lets an unchanged credential keep its stored secret on edit", () => {
    expect(
      isJiraCredentialComplete(
        completeness({ isEditing: true, secret: "", originalAuthMode: "basic" }),
      ),
    ).toBe(true);
  });

  it("requires a new secret when the auth mode changes on edit", () => {
    const input = completeness({
      isEditing: true,
      secret: "",
      authMode: "pat",
      originalAuthMode: "basic",
    });
    expect(isJiraCredentialComplete(input)).toBe(false);
    expect(isJiraCredentialComplete({ ...input, secret: "new-token" })).toBe(true);
  });

  it("requires a new secret when a PAT credential is switched to Cloud", () => {
    expect(
      isJiraCredentialComplete(
        completeness({
          isEditing: true,
          secret: "",
          deployment: "cloud",
          authMode: "pat",
          originalAuthMode: "pat",
        }),
      ),
    ).toBe(false);
  });

  it("requires a secret for a new credential", () => {
    expect(isJiraCredentialComplete(completeness({ secret: "" }))).toBe(false);
  });
});
