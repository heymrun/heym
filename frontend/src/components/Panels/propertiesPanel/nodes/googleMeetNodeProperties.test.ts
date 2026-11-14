import { computed, ref } from "vue";
import { describe, expect, it, vi } from "vitest";

import { GOOGLE_MEET_BUSY_DETAILS_OPTION } from "@/lib/googleMeetFields";
import { isBusyDetailsChecked, setBusyDetailsChecked } from "./googleMeetNodeProperties";

describe("isBusyDetailsChecked", () => {
  it("returns true when gmIncludeBusyDetails is true", () => {
    expect(isBusyDetailsChecked({ gmIncludeBusyDetails: true })).toBe(true);
    expect(isBusyDetailsChecked({ gmIncludeBusyDetails: true, gmIncludeBusyTitles: false })).toBe(true);
  });

  it("returns false when gmIncludeBusyDetails is false, even if legacy gmIncludeBusyTitles is true", () => {
    expect(isBusyDetailsChecked({ gmIncludeBusyDetails: false })).toBe(false);
    expect(isBusyDetailsChecked({ gmIncludeBusyDetails: false, gmIncludeBusyTitles: true })).toBe(false);
  });

  it("ensures explicit null displays unchecked, taking precedence over legacy true", () => {
    expect(isBusyDetailsChecked({ gmIncludeBusyDetails: null, gmIncludeBusyTitles: true })).toBe(false);
    expect(isBusyDetailsChecked({ gmIncludeBusyDetails: null })).toBe(false);
  });

  it("ensures explicitly present undefined displays unchecked and overrides legacy true", () => {
    expect(isBusyDetailsChecked({ gmIncludeBusyDetails: undefined, gmIncludeBusyTitles: true })).toBe(false);
  });

  it("falls back to legacy gmIncludeBusyTitles when gmIncludeBusyDetails is absent", () => {
    expect(isBusyDetailsChecked({ gmIncludeBusyTitles: true })).toBe(true);
    expect(isBusyDetailsChecked({ gmIncludeBusyTitles: false })).toBe(false);
  });

  it("returns false for empty object, null, or undefined data", () => {
    expect(isBusyDetailsChecked({})).toBe(false);
    expect(isBusyDetailsChecked(null)).toBe(false);
    expect(isBusyDetailsChecked(undefined)).toBe(false);
  });
});

describe("setBusyDetailsChecked and checkbox write behavior", () => {
  it("writes gmIncludeBusyDetails: true when checked", () => {
    const updateNodeData = vi.fn();
    setBusyDetailsChecked(true, updateNodeData);
    expect(updateNodeData).toHaveBeenCalledWith(GOOGLE_MEET_BUSY_DETAILS_OPTION.key, true);
    expect(updateNodeData).toHaveBeenCalledWith("gmIncludeBusyDetails", true);
  });

  it("writes gmIncludeBusyDetails: false when unchecked", () => {
    const updateNodeData = vi.fn();
    setBusyDetailsChecked(false, updateNodeData);
    expect(updateNodeData).toHaveBeenCalledWith(GOOGLE_MEET_BUSY_DETAILS_OPTION.key, false);
    expect(updateNodeData).toHaveBeenCalledWith("gmIncludeBusyDetails", false);
  });

  it("ensures unchecking a legacy node with gmIncludeBusyTitles: true writes gmIncludeBusyDetails: false so the new key takes precedence", () => {
    const nodeData: Record<string, unknown> = { gmIncludeBusyTitles: true };
    const updateNodeData = vi.fn((key: string, value: unknown) => {
      nodeData[key] = value;
    });

    // Before unchecking, legacy node displays as checked
    expect(isBusyDetailsChecked(nodeData)).toBe(true);

    // Uncheck the checkbox
    setBusyDetailsChecked(false, updateNodeData);

    expect(updateNodeData).toHaveBeenCalledWith("gmIncludeBusyDetails", false);
    expect(nodeData.gmIncludeBusyDetails).toBe(false);
    // After unchecking, gmIncludeBusyDetails: false overrides gmIncludeBusyTitles: true
    expect(isBusyDetailsChecked(nodeData)).toBe(false);
  });

  it("ensures re-checking after unchecking a legacy node writes gmIncludeBusyDetails: true", () => {
    const nodeData: Record<string, unknown> = {
      gmIncludeBusyTitles: true,
      gmIncludeBusyDetails: false,
    };
    const updateNodeData = vi.fn((key: string, value: unknown) => {
      nodeData[key] = value;
    });

    expect(isBusyDetailsChecked(nodeData)).toBe(false);

    setBusyDetailsChecked(true, updateNodeData);

    expect(updateNodeData).toHaveBeenCalledWith("gmIncludeBusyDetails", true);
    expect(nodeData.gmIncludeBusyDetails).toBe(true);
    expect(isBusyDetailsChecked(nodeData)).toBe(true);
  });

  it("updates reactive state and computed checkbox value when toggled on a legacy node", () => {
    const node = ref({
      data: { gmIncludeBusyTitles: true } as Record<string, unknown>,
    });
    const updateNodeData = (key: string, value: unknown) => {
      node.value.data = { ...node.value.data, [key]: value };
    };
    const isChecked = computed({
      get(): boolean {
        return isBusyDetailsChecked(node.value.data);
      },
      set(val: boolean): void {
        setBusyDetailsChecked(val, updateNodeData);
      },
    });

    // Legacy node initially checked
    expect(isChecked.value).toBe(true);

    // Unchecking sets gmIncludeBusyDetails: false and updates computed isChecked to false
    isChecked.value = false;
    expect(node.value.data.gmIncludeBusyDetails).toBe(false);
    expect(isChecked.value).toBe(false);

    // Checking sets gmIncludeBusyDetails: true and updates computed isChecked to true
    isChecked.value = true;
    expect(node.value.data.gmIncludeBusyDetails).toBe(true);
    expect(isChecked.value).toBe(true);
  });

  it("handles input change event and propagates checked state to updateNodeData", () => {
    const updateNodeData = vi.fn();
    const handleEvent = (event: { target: { checked: boolean } }) => {
      setBusyDetailsChecked(event.target.checked, updateNodeData);
    };

    handleEvent({ target: { checked: false } });
    expect(updateNodeData).toHaveBeenCalledWith("gmIncludeBusyDetails", false);

    handleEvent({ target: { checked: true } });
    expect(updateNodeData).toHaveBeenCalledWith("gmIncludeBusyDetails", true);
  });
});
