export type JiraDeployment = "cloud" | "data_center";
export type JiraAuthMode = "basic" | "pat";

export interface JiraCredentialForm {
  email: string;
  secret: string;
  baseUrl: string;
  deployment: JiraDeployment;
  apiVersion: string;
  authMode: JiraAuthMode;
}

export interface JiraCompletenessInput extends JiraCredentialForm {
  isEditing: boolean;
  /** Auth mode the credential was saved with; undefined for a new credential. */
  originalAuthMode?: JiraAuthMode;
}

/**
 * Normalize the stored auth mode. A credential saved before `auth_mode` existed
 * has none, and that always means Basic auth.
 */
export function normalizeJiraAuthMode(value: unknown): JiraAuthMode {
  return value === "pat" ? "pat" : "basic";
}

/** PAT auth only exists for Data Center / Server, so Cloud is always Basic. */
export function effectiveJiraAuthMode(form: JiraCredentialForm): JiraAuthMode {
  return form.deployment === "data_center" ? form.authMode : "basic";
}

export function buildJiraCredentialConfig(form: JiraCredentialForm): Record<string, string> {
  const authMode = effectiveJiraAuthMode(form);
  const config: Record<string, string> = {
    api_token: form.secret.trim(),
    base_url: form.baseUrl.trim(),
    deployment: form.deployment,
    auth_mode: authMode,
  };
  if (authMode === "basic") {
    config.email = form.email.trim();
  }
  const apiVersion = form.deployment === "data_center" ? "2" : form.apiVersion.trim();
  if (apiVersion) {
    config.api_version = apiVersion;
  }
  return config;
}

/**
 * A stored secret can be kept on edit only while the auth mode is unchanged:
 * the backend drops it on a mode switch, so the user must enter a new one.
 */
function canKeepStoredSecret(input: JiraCompletenessInput): boolean {
  return (
    input.isEditing &&
    input.originalAuthMode !== undefined &&
    input.originalAuthMode === effectiveJiraAuthMode(input)
  );
}

export function isJiraCredentialComplete(input: JiraCompletenessInput): boolean {
  if (!input.baseUrl.trim()) {
    return false;
  }
  if (effectiveJiraAuthMode(input) === "basic" && !input.email.trim()) {
    return false;
  }
  return !!input.secret.trim() || canKeepStoredSecret(input);
}

export function jiraSecretLabel(deployment: JiraDeployment, authMode: JiraAuthMode): string {
  if (deployment === "cloud") {
    return "API Token";
  }
  return authMode === "pat" ? "Personal Access Token" : "Password";
}

export function jiraAuthHelpText(deployment: JiraDeployment, authMode: JiraAuthMode): string {
  if (deployment === "cloud") {
    return "Jira Cloud uses an Atlassian account email and API token.";
  }
  if (authMode === "pat") {
    return "Personal access tokens are sent as a Bearer token and need Jira Data Center / Server 8.14 or later.";
  }
  return "Data Center / Server Basic auth uses a Jira username and password.";
}

export function jiraIncompleteMessage(form: JiraCredentialForm): string {
  const authMode = effectiveJiraAuthMode(form);
  if (form.deployment === "cloud") {
    return "Enter Jira email, API token, and base URL to test the connection.";
  }
  return authMode === "pat"
    ? "Enter the personal access token and base URL to test the connection."
    : "Enter Jira username, password, and base URL to test the connection.";
}
