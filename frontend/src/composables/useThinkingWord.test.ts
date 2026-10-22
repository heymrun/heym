import { describe, expect, it } from "vitest";

import { THINKING_WORDS, pickThinkingWord } from "@/composables/useThinkingWord";

describe("pickThinkingWord", () => {
  it("never repeats the previous word", () => {
    for (const previous of THINKING_WORDS) {
      for (const roll of [0, 0.5, 0.999]) {
        expect(pickThinkingWord(previous, () => roll)).not.toBe(previous);
      }
    }
  });

  it("only returns listed words", () => {
    expect(THINKING_WORDS).toContain(pickThinkingWord(null, () => 0.42));
    expect(THINKING_WORDS).toContain("Heyming");
    expect(THINKING_WORDS).toContain("Flowing");
  });
});
