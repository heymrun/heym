import { describe, expect, it } from "vitest";

import {
  AI_PANEL_GAP,
  AI_PANEL_MIN_HEIGHT,
  AI_PANEL_MIN_WIDTH,
  clampAiPanelFrame,
  defaultAiPanelFrame,
  estimateAiPanelWidth,
} from "@/composables/useAiAssistantPanelFrame";

describe("estimateAiPanelWidth", () => {
  it("starts between 360 and 620 and stays inside the side gaps", () => {
    expect(estimateAiPanelWidth(800)).toBe(360);
    expect(estimateAiPanelWidth(1600)).toBe(544);
    expect(estimateAiPanelWidth(2400)).toBe(620);
    expect(estimateAiPanelWidth(400)).toBe(400 - AI_PANEL_GAP * 2);
  });
});

describe("defaultAiPanelFrame", () => {
  it("anchors the panel to the bottom-right under the editor toolbar", () => {
    const frame = defaultAiPanelFrame({ width: 1440, height: 900 });
    const width = estimateAiPanelWidth(1440);

    expect(frame.left).toBe(1440 - AI_PANEL_GAP - width);
    expect(frame.top).toBe(64 + AI_PANEL_GAP);
    expect(frame.width).toBe(width);
    expect(frame.height).toBe(900 - frame.top - AI_PANEL_GAP);
  });
});

describe("clampAiPanelFrame", () => {
  const viewport = { width: 1200, height: 800 };

  it("keeps a dragged panel inside the viewport and above the minimum size", () => {
    const frame = clampAiPanelFrame(
      { left: -40, top: 2000, width: 80, height: 100 },
      viewport,
    );

    expect(frame.left).toBe(AI_PANEL_GAP);
    expect(frame.width).toBe(AI_PANEL_MIN_WIDTH);
    expect(frame.height).toBe(AI_PANEL_MIN_HEIGHT);
    expect(frame.top).toBe(800 - AI_PANEL_MIN_HEIGHT - AI_PANEL_GAP);
  });

  it("lets the panel grow in width and height up to the viewport gaps", () => {
    const frame = clampAiPanelFrame(
      { left: 24, top: 24, width: 4000, height: 4000 },
      viewport,
    );

    expect(frame.width).toBe(1200 - AI_PANEL_GAP * 2);
    expect(frame.height).toBe(800 - AI_PANEL_GAP * 2);
  });

  it("shrinks width from the left edge without moving the right edge", () => {
    const origin = { left: 400, top: 120, width: 480, height: 360 };
    const nextWidth = 360;
    const frame = clampAiPanelFrame(
      {
        ...origin,
        left: origin.left + (origin.width - nextWidth),
        width: nextWidth,
      },
      viewport,
    );

    expect(frame.width).toBe(360);
    expect(frame.left + frame.width).toBe(origin.left + origin.width);
  });
});
