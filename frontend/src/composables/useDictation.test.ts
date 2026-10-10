import { describe, expect, it, vi } from "vitest";

import { createDictation, type SpeechRecognitionConstructor } from "@/composables/useDictation";

class FakeRecognition {
  static last: FakeRecognition | null = null;
  lang = "";
  continuous = false;
  interimResults = false;
  onresult: ((event: unknown) => void) | null = null;
  onerror: ((event: unknown) => void) | null = null;
  onend: (() => void) | null = null;
  start = vi.fn();
  stop = vi.fn();

  constructor() {
    FakeRecognition.last = this;
  }
}

const Recognition = FakeRecognition as unknown as SpeechRecognitionConstructor;

function session(): {
  dictation: ReturnType<typeof createDictation>;
  onStart: ReturnType<typeof vi.fn>;
  onTranscript: ReturnType<typeof vi.fn>;
  onStop: ReturnType<typeof vi.fn>;
} {
  const onStart = vi.fn();
  const onTranscript = vi.fn();
  const onStop = vi.fn();
  const dictation = createDictation({ lang: "en-US", onStart, onTranscript, onStop });
  return { dictation, onStart, onTranscript, onStop };
}

describe("createDictation", () => {
  it("does nothing in a browser without speech recognition", () => {
    const { dictation, onStart } = session();

    dictation.connect(undefined);
    dictation.toggle();

    expect(dictation.supported.value).toBe(false);
    expect(dictation.listening.value).toBe(false);
    expect(onStart).not.toHaveBeenCalled();
  });

  it("streams the whole transcript and keeps listening when the browser ends the session", () => {
    const { dictation, onStart, onTranscript } = session();
    dictation.connect(Recognition);
    const recognition = FakeRecognition.last!;

    dictation.toggle();
    recognition.onresult?.({
      results: [
        { isFinal: true, 0: { transcript: "Send the report " } },
        { isFinal: false, 0: { transcript: "to the sales team" } },
      ],
    });
    recognition.onend?.();

    expect(recognition.lang).toBe("en-US");
    expect(onStart).toHaveBeenCalledOnce();
    expect(onTranscript).toHaveBeenCalledWith("Send the report to the sales team");
    expect(recognition.start).toHaveBeenCalledTimes(2);
    expect(dictation.listening.value).toBe(true);
  });

  it("stops on the second toggle and lets the host clean up the text", () => {
    const { dictation, onStop } = session();
    dictation.connect(Recognition);

    dictation.toggle();
    dictation.toggle();

    expect(FakeRecognition.last!.stop).toHaveBeenCalledOnce();
    expect(dictation.listening.value).toBe(false);
    expect(onStop).toHaveBeenCalledOnce();
  });

  it("stops listening after a recognition error instead of restarting", () => {
    const { dictation } = session();
    dictation.connect(Recognition);
    const recognition = FakeRecognition.last!;

    dictation.toggle();
    recognition.onerror?.(new Event("error"));
    recognition.onend?.();

    expect(dictation.listening.value).toBe(false);
    expect(recognition.start).toHaveBeenCalledOnce();
  });
});
