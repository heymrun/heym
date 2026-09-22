import { effectScope, ref } from "vue";
import type { EffectScope, Ref } from "vue";

import { afterEach, describe, expect, it } from "vitest";

import type { ExecutionToken, ExecutionTokenListItem } from "@/types/workflow";

import { useExecutionTokens } from "./useExecutionTokens";

const scopes: EffectScope[] = [];

function setup(workflowId: Ref<string> = ref("workflow-a")): ReturnType<typeof useExecutionTokens> {
  const scope = effectScope();
  scopes.push(scope);
  return scope.run(() => useExecutionTokens(workflowId))!;
}

function listed(id: string): ExecutionTokenListItem {
  return {
    id, creator_id: "creator", creator_email: "creator@example.com",
    expires_at: "2099-01-01T00:00:00Z", created_at: "2026-01-01T00:00:00Z", revoked: false,
  };
}

function created(id: string): ExecutionToken {
  const { expires_at, created_at, revoked } = listed(id);
  return { id, expires_at, created_at, revoked, token: `fresh-value-${id}` };
}

afterEach(() => {
  for (const scope of scopes.splice(0)) scope.stop();
});

describe("execution token values in the editor session", () => {
  it("does not select or reveal metadata-only tokens, including another creator's tokens", () => {
    const state = setup();
    const token = listed("existing");
    state.replaceTokens([token]);
    state.selectToken(token);

    expect(state.selectedTokenId.value).toBeNull();
    expect(state.canUseToken(token)).toBe(false);
    expect(state.tokenValue(token)).toBeUndefined();
    expect(state.bearerToken.value).toBe("<your-execution-token>");
    expect(state.executionTokens.value).toHaveLength(1);
  });

  it("keeps create-time values separate and preserves them when the dialog reloads metadata", () => {
    const state = setup();
    state.rememberCreatedToken(created("fresh"));
    expect(state.bearerToken.value).toBe("fresh-value-fresh");
    expect(state.executionTokens.value[0]).not.toHaveProperty("token");

    state.replaceTokens([listed("existing"), listed("fresh")]);
    state.selectToken(listed("existing"));
    expect(state.selectedTokenId.value).toBe("fresh");
    expect(state.bearerToken.value).toBe("fresh-value-fresh");
  });

  it("does not carry values into a new editor instance after a page reload", () => {
    const previous = setup();
    previous.rememberCreatedToken(created("fresh"));
    const reloaded = setup();
    reloaded.replaceTokens([listed("fresh")]);

    expect(reloaded.bearerToken.value).toBe("<your-execution-token>");
    expect(reloaded.canUseToken(listed("fresh"))).toBe(false);
  });

  it("forgets a revoked value and only falls back to another value created in this session", () => {
    const state = setup();
    state.replaceTokens([listed("existing")]);
    state.rememberCreatedToken(created("first"));
    state.rememberCreatedToken(created("second"));
    state.tokenVisibility.value.second = true;

    state.markRevoked("second");
    expect(state.bearerToken.value).toBe("fresh-value-first");
    expect(state.tokenVisibility.value.second).toBeUndefined();
    state.markRevoked("first");
    expect(state.bearerToken.value).toBe("<your-execution-token>");
    expect(state.selectedTokenId.value).toBeNull();
  });

  it.each(["revoked", "expired", "missing"])("forgets values reported as %s on refresh", (reason) => {
    const state = setup();
    state.rememberCreatedToken(created("fresh"));
    const updated = listed("fresh");
    if (reason === "revoked") updated.revoked = true;
    if (reason === "expired") updated.expires_at = "2020-01-01T00:00:00Z";
    state.replaceTokens(reason === "missing" ? [] : [updated]);

    expect(state.bearerToken.value).toBe("<your-execution-token>");
    state.replaceTokens([listed("fresh")]);
    expect(state.tokenValue(listed("fresh"))).toBeUndefined();
  });

  it("clears metadata, selection and secrets on a workflow change", () => {
    const workflowId = ref("workflow-a");
    const state = setup(workflowId);
    state.rememberCreatedToken(created("fresh"));
    state.tokenVisibility.value.fresh = true;
    workflowId.value = "workflow-b";

    expect(state.executionTokens.value).toEqual([]);
    expect(state.selectedTokenId.value).toBeNull();
    expect(state.tokenVisibility.value).toEqual({});
    workflowId.value = "workflow-a";
    state.replaceTokens([listed("fresh")]);
    expect(state.bearerToken.value).toBe("<your-execution-token>");
  });
});
