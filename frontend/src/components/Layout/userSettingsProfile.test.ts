import { describe, expect, it } from "vitest";

import type { User } from "@/types/auth";
import { mergeFreshProfile } from "@/components/Layout/userSettingsProfile";

function user(overrides: Partial<User> = {}): User {
  return {
    id: "u1",
    email: "ada@example.com",
    name: "Ada",
    is_admin: false,
    user_rules: "Answer in English",
    tts_credential_id: null,
    tts_voice_id: null,
    preferred_credential_id: null,
    preferred_model: null,
    created_at: "2026-11-08T00:00:00Z",
    ...overrides,
  };
}

describe("mergeFreshProfile", () => {
  it("shows what a chat saved since the dialog's cached copy", () => {
    const cached = user();
    const fresh = user({ user_rules: "Answer in English\nPrefers short answers" });
    const merged = mergeFreshProfile({ name: "Ada", userRules: "Answer in English" }, cached, fresh);
    expect(merged.userRules).toBe("Answer in English\nPrefers short answers");
  });

  it("keeps what the user already typed", () => {
    const cached = user();
    const fresh = user({ user_rules: "Something from chat", name: "Ada L." });
    const merged = mergeFreshProfile({ name: "Ada Lovelace", userRules: "My own edit" }, cached, fresh);
    expect(merged).toEqual({ name: "Ada Lovelace", userRules: "My own edit" });
  });

  it("treats null rules as empty text", () => {
    const cached = user({ user_rules: null });
    const fresh = user({ user_rules: "Prefers short answers" });
    const merged = mergeFreshProfile({ name: "Ada", userRules: "" }, cached, fresh);
    expect(merged.userRules).toBe("Prefers short answers");
  });
});
