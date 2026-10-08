import { createSSRApp, h, type Component } from "vue";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderToString } from "vue/server-renderer";

import Dialog from "@/components/ui/Dialog.vue";

interface DialogBackHistoryOptions {
  enabled: () => boolean;
  isOpen: () => boolean;
  onBack: () => void;
}

let mockStack: symbol[] = [];
let mockIsTopmost = true;
let mockIsBottommost = true;
let mockOverlayZ = 50;
let keydownListeners: ((event: KeyboardEvent) => void)[] = [];
let capturedBackOptions: DialogBackHistoryOptions | null = null;
let capturedUnmountedCb: (() => void) | null = null;

const mockPushHistory = vi.fn();
const mockRemoveHistory = vi.fn();
const mockAddToStack = vi.fn();
const mockRemoveFromStack = vi.fn();

vi.mock("vue", async (importOriginal) => {
  const actual = await importOriginal<typeof import("vue")>();
  return {
    ...actual,
    onUnmounted: (cb: () => void): void => {
      capturedUnmountedCb = cb;
    },
  };
});

vi.mock("@/composables/useDialogStack", () => ({
  addToDialogStack: (id: symbol): void => {
    mockAddToStack(id);
    mockStack = [...mockStack.filter((s) => s !== id), id];
    (globalThis as unknown as { document: { body: { style: { overflow: string } } } }).document.body.style.overflow =
      mockStack.length > 0 ? "hidden" : "";
  },
  removeFromDialogStack: (id: symbol): void => {
    mockRemoveFromStack(id);
    mockStack = mockStack.filter((s) => s !== id);
    (globalThis as unknown as { document: { body: { style: { overflow: string } } } }).document.body.style.overflow =
      mockStack.length > 0 ? "hidden" : "";
  },
  isTopmostDialog: (id: symbol): boolean =>
    mockIsTopmost ? mockStack[mockStack.length - 1] === id : false,
  isBottommostDialog: (id: symbol): boolean =>
    mockIsBottommost ? mockStack[0] === id : false,
  dialogStackPosition: (id: symbol): number => Math.max(mockStack.indexOf(id), 0),
  hasOpenDialog: (): boolean => mockStack.length > 0,
  overlayZIndex: (): number => mockOverlayZ,
}));

vi.mock("@/composables/useDialogBackHistory", () => ({
  useDialogBackHistory: (options: DialogBackHistoryOptions) => {
    capturedBackOptions = options;
    return {
      pushDialogHistoryEntry: mockPushHistory,
      removeDialogHistoryEntry: mockRemoveHistory,
    };
  },
}));

beforeEach(() => {
  mockStack = [];
  mockIsTopmost = true;
  mockIsBottommost = true;
  mockOverlayZ = 50;
  keydownListeners = [];
  capturedBackOptions = null;
  capturedUnmountedCb = null;
  vi.clearAllMocks();

  (globalThis as unknown as { window: unknown }).window = {
    addEventListener: vi.fn((event: string, fn: (e: KeyboardEvent) => void) => {
      if (event === "keydown") keydownListeners.push(fn);
    }),
    removeEventListener: vi.fn((event: string, fn: (e: KeyboardEvent) => void) => {
      if (event === "keydown") {
        keydownListeners = keydownListeners.filter((f) => f !== fn);
      }
    }),
  };

  (globalThis as unknown as { document: unknown }).document = {
    body: {
      style: { overflow: "" },
    },
    createElement: (): { style: Record<string, unknown> } => ({ style: {} }),
  };
});

async function renderDialog(
  props: Record<string, unknown> = {},
  slots: Record<string, () => unknown> = {},
): Promise<string> {
  const app = createSSRApp({
    render: () => h(Dialog as Component, props, slots),
  });
  const ctx: Record<string, unknown> = {};
  await renderToString(app, ctx);
  return ((ctx.teleports as Record<string, string> | undefined)?.body) || "";
}

function createKeyboardEvent(overrides: Partial<KeyboardEvent> = {}): KeyboardEvent {
  return {
    key: "Escape",
    defaultPrevented: false,
    preventDefault: vi.fn(),
    stopImmediatePropagation: vi.fn(),
    ...overrides,
  } as unknown as KeyboardEvent;
}

describe("Dialog visibility and structure", () => {
  it("renders nothing into the teleport target when open is false", async () => {
    const html = await renderDialog({ open: false, title: "Hidden modal" });

    expect(html).not.toContain("Hidden modal");
    expect(html).not.toContain("dialog-content");
    expect(mockRemoveFromStack).toHaveBeenCalled();
    expect(mockRemoveHistory).toHaveBeenCalled();
    expect(keydownListeners.length).toBe(0);
  });

  it("renders container, backdrop, content, close button, and body when open is true", async () => {
    const html = await renderDialog({ open: true, title: "Visible modal" });

    expect(html).toContain("dialog-backdrop");
    expect(html).toContain("dialog-content");
    expect(html).toContain("dialog-header");
    expect(html).toContain("dialog-body");
    expect(html).toContain("Visible modal");
    expect(mockAddToStack).toHaveBeenCalled();
    expect(mockPushHistory).toHaveBeenCalled();
    expect(keydownListeners.length).toBe(1);
    expect(
      (globalThis as unknown as { document: { body: { style: { overflow: string } } } }).document.body.style.overflow,
    ).toBe("hidden");
  });
});

describe("Dialog title, subtitle, and slots", () => {
  it("is a modal dialog named by its title, with named window buttons", async () => {
    const html = await renderDialog({ open: true, title: "New credential", allowFullscreen: true });
    const titleId = html.match(/<h2[^>]* id="([^"]+)"/)?.[1];

    expect(html).toContain('role="dialog"');
    expect(html).toContain('aria-modal="true"');
    expect(titleId).toBeTruthy();
    expect(html).toContain(`aria-labelledby="${titleId}"`);
    expect(html).toContain('aria-label="Close"');
    expect(html).toContain('aria-label="Full screen"');
  });

  it("leaves aria-labelledby out when there is no title", async () => {
    const html = await renderDialog({ open: true });

    expect(html).toContain('role="dialog"');
    expect(html).not.toContain("aria-labelledby");
  });

  it("renders title text and tooltip attribute on h2", async () => {
    const html = await renderDialog({ open: true, title: "Export Workflow" });

    expect(html).toMatch(/<h2[^>]* title="Export Workflow"/);
    expect(html).toContain("Export Workflow</h2>");
    expect(html).toContain("text-sm sm:text-base md:text-lg");
  });

  it("applies custom titleClass when provided", async () => {
    const html = await renderDialog({
      open: true,
      title: "Custom Title",
      titleClass: "text-2xl font-bold text-red-500",
    });

    expect(html).toContain("text-2xl font-bold text-red-500");
    expect(html).not.toContain("text-sm sm:text-base md:text-lg");
  });

  it("omits the title and subtitle wrapper when neither is provided", async () => {
    const html = await renderDialog({ open: true });

    expect(html).not.toContain("<h2");
  });

  it("renders subtitle slot when provided", async () => {
    const html = await renderDialog(
      { open: true, title: "Parent title" },
      { subtitle: () => h("span", "Sub heading description") },
    );

    expect(html).toContain("Sub heading description");
    expect(html).toContain("line-clamp-1 leading-snug sm:leading-none");
  });

  it("renders default slot content inside dialog-body", async () => {
    const html = await renderDialog(
      { open: true, title: "Form Dialog" },
      { default: () => h("form", { id: "test-form" }, "Form Inputs") },
    );

    expect(html).toContain('<form id="test-form">Form Inputs</form>');
    expect(html).toContain("dialog-body");
  });

  it("switches header layout to grid when header-actions slot is provided", async () => {
    const defaultHtml = await renderDialog({ open: true, title: "No Actions" });
    expect(defaultHtml).toContain("flex items-center justify-between");
    expect(defaultHtml).not.toContain("grid grid-cols-[minmax(0,1fr)_auto]");

    const actionsHtml = await renderDialog(
      { open: true, title: "With Actions" },
      { "header-actions": () => h("button", "Save All") },
    );
    expect(actionsHtml).toContain("grid grid-cols-[minmax(0,1fr)_auto]");
    expect(actionsHtml).toContain("Save All");
    expect(actionsHtml).toContain("h-5 w-px bg-border/60 shrink-0 hidden sm:block");
  });

  it("renders header-trailing slot before window control buttons", async () => {
    const html = await renderDialog(
      { open: true, title: "Trailing Dialog" },
      { "header-trailing": () => h("span", { class: "badge" }, "Status Badge") },
    );

    expect(html).toContain("Status Badge");
  });
});

describe("Dialog sizes and styling", () => {
  const sizeMap: Record<string, string> = {
    sm: "max-w-sm",
    md: "max-w-md",
    lg: "max-w-lg",
    xl: "max-w-xl",
    "2xl": "max-w-2xl",
    "3xl": "max-w-3xl",
    "4xl": "max-w-4xl",
    "5xl": "max-w-5xl",
    "6xl": "max-w-6xl",
    "7xl": "max-w-7xl",
    full: "max-w-[95vw] md:max-w-4xl",
  };

  for (const [size, expectedClass] of Object.entries(sizeMap)) {
    it(`applies ${expectedClass} for size="${size}"`, async () => {
      const html = await renderDialog({ open: true, size });
      expect(html).toContain(expectedClass);
    });
  }

  it("defaults to max-w-lg when size is omitted", async () => {
    const html = await renderDialog({ open: true });
    expect(html).toContain("max-w-lg");
  });

  it("falls back to max-w-lg for unknown size value", async () => {
    const html = await renderDialog({ open: true, size: "unrecognized" as unknown });
    expect(html).toContain("max-w-lg");
  });

  it("appends custom contentClass to dialog-content", async () => {
    const html = await renderDialog({
      open: true,
      contentClass: "!max-w-6xl custom-panel-override",
    });

    expect(html).toContain("!max-w-6xl custom-panel-override");
  });
});

describe("Dialog fullscreen behavior", () => {
  it("omits fullscreen toggle button when allowFullscreen is false", async () => {
    const html = await renderDialog({ open: true, allowFullscreen: false });

    expect(html).not.toContain("lucide-maximize2");
    expect(html).not.toContain("lucide-minimize2");
  });

  it("renders fullscreen button with Maximize2 icon when allowFullscreen is true", async () => {
    const html = await renderDialog({ open: true, allowFullscreen: true });

    expect(html).toContain("lucide-maximize2");
  });

  it("applies hidden sm:flex when hideFullscreenToggleOnMobile is true", async () => {
    const html = await renderDialog({
      open: true,
      allowFullscreen: true,
      hideFullscreenToggleOnMobile: true,
    });

    expect(html).toContain("hidden sm:flex");
  });

  it("applies flex when hideFullscreenToggleOnMobile is false", async () => {
    const html = await renderDialog({
      open: true,
      allowFullscreen: true,
      hideFullscreenToggleOnMobile: false,
    });

    expect(html).toContain("flex");
  });

  it("renders fullscreen layout and Minimize2 icon when defaultFullscreen is true", async () => {
    const html = await renderDialog({
      open: true,
      allowFullscreen: true,
      defaultFullscreen: true,
    });

    expect(html).toContain("max-w-[100vw] w-[100vw] h-[100vh] !rounded-none");
    expect(html).toContain("max-h-[100dvh]");
    expect(html).toContain("lucide-minimize2");
  });
});

describe("Dialog keyboard Escape handling", () => {
  it("ignores non-Escape keys", async () => {
    const onClose = vi.fn();
    const onEscape = vi.fn();
    await renderDialog({ open: true, onClose, onEscape });

    const handler = keydownListeners[0];
    const event = createKeyboardEvent({ key: "Enter" });
    handler(event);

    expect(onEscape).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("emits escape and close events on Escape when dialog is topmost", async () => {
    const onClose = vi.fn();
    const onEscape = vi.fn();
    await renderDialog({ open: true, onClose, onEscape });

    const handler = keydownListeners[0];
    const event = createKeyboardEvent();
    handler(event);

    expect(onEscape).toHaveBeenCalledWith(event);
    expect(onClose).toHaveBeenCalled();
    expect(event.preventDefault).toHaveBeenCalled();
    expect(event.stopImmediatePropagation).toHaveBeenCalled();
  });

  it("does not close when closeOnEscape is false", async () => {
    const onClose = vi.fn();
    const onEscape = vi.fn();
    await renderDialog({ open: true, closeOnEscape: false, onClose, onEscape });

    const handler = keydownListeners[0];
    const event = createKeyboardEvent();
    handler(event);

    expect(onEscape).toHaveBeenCalledWith(event);
    expect(onClose).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("does not close when event.defaultPrevented is true", async () => {
    const onClose = vi.fn();
    const onEscape = vi.fn();
    await renderDialog({ open: true, onClose, onEscape });

    const handler = keydownListeners[0];
    const event = createKeyboardEvent({ defaultPrevented: true });
    handler(event);

    expect(onEscape).toHaveBeenCalledWith(event);
    expect(onClose).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });

  it("exits fullscreen on first Escape, then closes on second Escape when allowFullscreen is true", async () => {
    const onClose = vi.fn();
    const onEscape = vi.fn();
    await renderDialog({
      open: true,
      allowFullscreen: true,
      defaultFullscreen: true,
      onClose,
      onEscape,
    });

    const handler = keydownListeners[0];

    // First Escape exits fullscreen
    const event1 = createKeyboardEvent();
    handler(event1);
    expect(onEscape).toHaveBeenCalledTimes(1);
    expect(onClose).not.toHaveBeenCalled();
    expect(event1.preventDefault).toHaveBeenCalled();

    // Second Escape closes the dialog
    const event2 = createKeyboardEvent();
    handler(event2);
    expect(onEscape).toHaveBeenCalledTimes(2);
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(event2.preventDefault).toHaveBeenCalled();
  });

  it("closes immediately on Escape when defaultFullscreen is true but allowFullscreen is false", async () => {
    const onClose = vi.fn();
    const onEscape = vi.fn();
    await renderDialog({
      open: true,
      allowFullscreen: false,
      defaultFullscreen: true,
      onClose,
      onEscape,
    });

    const handler = keydownListeners[0];
    const event = createKeyboardEvent();
    handler(event);

    expect(onEscape).toHaveBeenCalledTimes(1);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("ignores Escape when dialog is not topmost in the stack", async () => {
    mockIsTopmost = false;
    const onClose = vi.fn();
    const onEscape = vi.fn();
    await renderDialog({ open: true, onClose, onEscape });

    const handler = keydownListeners[0];
    const event = createKeyboardEvent();
    handler(event);

    expect(onEscape).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    expect(event.preventDefault).not.toHaveBeenCalled();
  });
});

describe("Dialog stacking and backdrop nesting", () => {
  it("renders non-nested backdrop and base zIndex for bottommost dialog", async () => {
    mockIsBottommost = true;
    mockOverlayZ = 50;
    const html = await renderDialog({ open: true });

    expect(html).toContain('style="z-index:50;"');
    expect(html).toContain('class="dialog-backdrop fixed inset-0"');
    expect(html).not.toContain("dialog-backdrop-nested");
  });

  it("applies dialog-backdrop-nested and dynamic z-index for stacked dialog", async () => {
    mockIsBottommost = false;
    mockOverlayZ = 70;
    const html = await renderDialog({ open: true });

    expect(html).toContain('style="z-index:70;"');
    expect(html).toContain("dialog-backdrop fixed inset-0 dialog-backdrop-nested");
  });
});

describe("Dialog back history and unmount integration", () => {
  it("passes closeOnBack to back history enabled option and invokes close on back", async () => {
    const onClose = vi.fn();
    await renderDialog({ open: true, closeOnBack: true, onClose });

    expect(capturedBackOptions).not.toBeNull();
    expect(capturedBackOptions?.enabled()).toBe(true);
    expect(capturedBackOptions?.isOpen()).toBe(true);

    capturedBackOptions?.onBack();
    expect(onClose).toHaveBeenCalled();
  });

  it("evaluates closeOnBack as false when prop is false", async () => {
    await renderDialog({ open: true, closeOnBack: false });

    expect(capturedBackOptions?.enabled()).toBe(false);
  });

  it("cleans up keydown listener, dialog stack, and back history on unmount", async () => {
    await renderDialog({ open: true });

    expect(capturedUnmountedCb).toBeTypeOf("function");
    capturedUnmountedCb?.();

    expect(
      (globalThis as unknown as { window: { removeEventListener: ReturnType<typeof vi.fn> } }).window.removeEventListener,
    ).toHaveBeenCalledWith("keydown", expect.any(Function), { capture: true });
    expect(mockRemoveFromStack).toHaveBeenCalled();
    expect(mockRemoveHistory).toHaveBeenCalled();
  });
});
