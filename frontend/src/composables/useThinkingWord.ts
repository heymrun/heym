import { ref, watch, type Ref } from "vue";
import { useIntervalFn } from "@vueuse/core";

/** Words the assistant cycles through while it waits for a reply. */
export const THINKING_WORDS: readonly string[] = [
  "Heyming",
  "Flowing",
  "Wiring",
  "Noding",
  "Branching",
  "Routing",
  "Orchestrating",
  "Chaining",
  "Mapping",
  "Looping",
  "Piping",
  "Weaving",
  "Tinkering",
  "Untangling",
  "Composing",
  "Brewing",
];

const ROTATE_MS = 2400;

/** A random word, never the same as `previous` so every change is visible. */
export function pickThinkingWord(previous: string | null, random: () => number = Math.random): string {
  const choices = THINKING_WORDS.filter((word) => word !== previous);
  return choices[Math.floor(random() * choices.length)] ?? THINKING_WORDS[0];
}

/** A word that changes every few seconds while `active` is true, and starts fresh each time. */
export function useThinkingWord(active: Readonly<Ref<boolean>>): Ref<string> {
  const word = ref(pickThinkingWord(null));
  const { pause, resume } = useIntervalFn(
    () => {
      word.value = pickThinkingWord(word.value);
    },
    ROTATE_MS,
    { immediate: false },
  );

  watch(
    active,
    (isActive) => {
      if (!isActive) {
        pause();
        return;
      }
      word.value = pickThinkingWord(word.value);
      resume();
    },
    { immediate: true },
  );

  return word;
}
