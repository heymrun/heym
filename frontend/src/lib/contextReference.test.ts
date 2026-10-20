import { describe, expect, it } from "vitest";

import { contextAccessor, contextReference, type ContextRoot } from "@/lib/contextReference";

const ROOTS: ContextRoot[] = ["credentials", "vars", "global"];

describe("contextReference", () => {
  it.each(ROOTS)("uses dot access under $%s for a plain identifier", (root) => {
    expect(contextReference(root, "MyToken")).toBe(`$${root}.MyToken`);
    expect(contextReference(root, "_key2")).toBe(`$${root}._key2`);
  });

  it.each(ROOTS)("keeps dot access under $%s for non-ASCII identifiers, as Python parses them", (root) => {
    for (const name of ["müşteri", "Müşteri", "naïve", "日本語"]) {
      expect(contextReference(root, name)).toBe(`$${root}.${name}`);
    }
  });

  it.each(ROOTS)("uses bracket access under $%s for names that are not plain identifiers", (root) => {
    for (const name of ["heym-codex-support", "my api key", "2fa", "token.v2", "a]b", ""]) {
      expect(contextReference(root, name)).toBe(`$${root}[${JSON.stringify(name)}]`);
    }
  });

  it.each(["global", "class", "None", "True", "from"])(
    "uses bracket access for the reserved word %s",
    (name) => {
      expect(contextReference("vars", name)).toBe(`$vars["${name}"]`);
    },
  );

  it("escapes quotes and backslashes in bracket access", () => {
    expect(contextReference("global", 'a"b\\c')).toBe('$global["a\\"b\\\\c"]');
  });
});

describe("contextAccessor", () => {
  it("returns the bare name for a plain identifier and a bracket for anything else", () => {
    expect(contextAccessor("MyToken")).toBe("MyToken");
    expect(contextAccessor("heym-codex-support")).toBe('["heym-codex-support"]');
  });
});
