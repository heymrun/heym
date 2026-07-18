import { describe, expect, it } from "vitest";

import type { CredentialListItem, LLMModel } from "@/types/credential";

import { createAiDefaultsResolver } from "./useAiDefaults";

function cred(id: string): CredentialListItem {
  return { id, name: id, type: "openai", masked_value: null, header_key: null, created_at: "" };
}

function model(id: string): LLMModel {
  return { id, name: id, is_reasoning: false, supports_batch: false };
}

const creds = [cred("c1"), cred("c2")];

describe("createAiDefaultsResolver", () => {
  it("prefers a saved selection over preferred and first", () => {
    const r = createAiDefaultsResolver({ preferredCredentialId: "c2", preferredModel: "m2" });
    expect(r.resolveCredentialId(creds, { savedCredentialId: "c1" })).toBe("c1");
  });

  it("falls back to preferred when nothing is saved", () => {
    const r = createAiDefaultsResolver({ preferredCredentialId: "c2", preferredModel: "m2" });
    expect(r.resolveCredentialId(creds, {})).toBe("c2");
  });

  it("falls back to first credential when preferred is not accessible", () => {
    const r = createAiDefaultsResolver({ preferredCredentialId: "gone", preferredModel: "m2" });
    expect(r.resolveCredentialId(creds, {})).toBe("c1");
  });

  it("resolveModel: saved wins, then preferred when its credential is chosen", () => {
    const r = createAiDefaultsResolver({ preferredCredentialId: "c2", preferredModel: "m2" });
    const models = [model("mA")];
    expect(r.resolveModel("c2", [...models, model("m2")], {})).toBe("m2");
    expect(r.resolveModel("c2", models, { savedModel: "mA" })).toBe("mA");
    // preferred model not in list, no saved -> null (caller keeps its own default)
    expect(r.resolveModel("c2", models, {})).toBeNull();
    // credential is not the preferred credential -> preferred model ignored
    expect(r.resolveModel("c1", [...models, model("m2")], {})).toBeNull();
  });

  it("preferredStatus flags an unresolvable preferred credential", () => {
    const r = createAiDefaultsResolver({ preferredCredentialId: "gone", preferredModel: "m2" });
    expect(r.preferredStatus(creds)).toBe("invalid");
    const ok = createAiDefaultsResolver({ preferredCredentialId: "c1", preferredModel: "m2" });
    expect(ok.preferredStatus(creds)).toBe("ok");
    const none = createAiDefaultsResolver({ preferredCredentialId: null, preferredModel: null });
    expect(none.preferredStatus(creds)).toBe("unset");
  });
});
