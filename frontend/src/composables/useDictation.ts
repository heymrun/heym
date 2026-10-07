import { onMounted, onUnmounted, ref, type Ref } from "vue";

// The Web Speech API is not in TypeScript's DOM library; these are the parts dictation uses.
interface SpeechRecognitionResultAlternative {
  transcript: string;
}

interface SpeechRecognitionResultItem {
  isFinal: boolean;
  0: SpeechRecognitionResultAlternative;
}

interface SpeechRecognitionResultList {
  length: number;
  [index: number]: SpeechRecognitionResultItem;
}

interface SpeechRecognitionEvent extends Event {
  results: SpeechRecognitionResultList;
}

interface SpeechRecognition extends EventTarget {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  onresult: ((event: SpeechRecognitionEvent) => void) | null;
  onerror: ((event: Event) => void) | null;
  onend: (() => void) | null;
  start(): void;
  stop(): void;
}

export type SpeechRecognitionConstructor = new () => SpeechRecognition;

interface SpeechRecognitionWindow extends Window {
  webkitSpeechRecognition?: SpeechRecognitionConstructor;
  SpeechRecognition?: SpeechRecognitionConstructor;
}

export interface DictationOptions {
  /** Recognition language, for example "en-US". */
  lang: string;
  /** Runs right before listening starts, for example to clear the message box. */
  onStart?: () => void;
  /** Receives the whole transcript so far, while the user speaks. */
  onTranscript: (text: string) => void;
  /** Runs when the user stops dictating, for example to clean up the text. */
  onStop?: () => void | Promise<void>;
}

export interface Dictation {
  supported: Ref<boolean>;
  listening: Ref<boolean>;
  toggle: () => void;
}

export interface DictationSession extends Dictation {
  connect: (Recognition: SpeechRecognitionConstructor | undefined) => void;
  disconnect: () => void;
}

/** Dictation over a speech recognition constructor; `useDictation` connects the browser's. */
export function createDictation(options: DictationOptions): DictationSession {
  const supported = ref(false);
  const listening = ref(false);
  let recognition: SpeechRecognition | null = null;

  function connect(Recognition: SpeechRecognitionConstructor | undefined): void {
    if (!Recognition) {
      supported.value = false;
      return;
    }
    supported.value = true;
    const instance = new Recognition();
    instance.lang = options.lang;
    instance.continuous = true;
    instance.interimResults = true;
    instance.onresult = (event: SpeechRecognitionEvent) => {
      const transcripts = Array.from(event.results).map((result) => result[0]?.transcript ?? "");
      const transcript = transcripts.join("").trim();
      if (transcript) options.onTranscript(transcript);
    };
    instance.onerror = () => {
      listening.value = false;
    };
    // Browsers end a continuous session on their own after a pause; keep going until stopped.
    instance.onend = () => {
      if (listening.value && recognition) {
        recognition.start();
      } else {
        listening.value = false;
      }
    };
    recognition = instance;
  }

  function toggle(): void {
    if (!recognition) return;
    if (listening.value) {
      listening.value = false;
      recognition.stop();
      void options.onStop?.();
      return;
    }
    options.onStart?.();
    listening.value = true;
    recognition.start();
  }

  function disconnect(): void {
    recognition?.stop();
  }

  return { supported, listening, toggle, connect, disconnect };
}

/** Dictation into a message box with the browser's speech recognition (no server call). */
export function useDictation(options: DictationOptions): Dictation {
  const session = createDictation(options);
  onMounted(() => {
    const recognitionWindow = window as SpeechRecognitionWindow;
    session.connect(recognitionWindow.SpeechRecognition || recognitionWindow.webkitSpeechRecognition);
  });
  onUnmounted(() => session.disconnect());
  return { supported: session.supported, listening: session.listening, toggle: session.toggle };
}
