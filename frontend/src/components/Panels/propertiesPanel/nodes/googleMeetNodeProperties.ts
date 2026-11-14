import { GOOGLE_MEET_BUSY_DETAILS_OPTION } from "@/lib/googleMeetFields";

/**
 * Determines whether the "Include Busy Event Details" checkbox should be checked.
 *
 * Precedence rule:
 * An explicitly present `gmIncludeBusyDetails` key always takes precedence over legacy
 * `gmIncludeBusyTitles`, including when its value is `null` or `false`. Explicit `null`
 * displays unchecked, matching backend behavior.
 * When `gmIncludeBusyDetails` is not present, legacy `gmIncludeBusyTitles` is used.
 */
export function isBusyDetailsChecked(data: Record<string, unknown> | undefined | null): boolean {
  if (!data) {
    return false;
  }
  if ("gmIncludeBusyDetails" in data) {
    return data.gmIncludeBusyDetails === true;
  }
  return data.gmIncludeBusyTitles === true;
}

/**
 * Updates the node data when the "Include Busy Event Details" checkbox is toggled.
 *
 * Always writes `gmIncludeBusyDetails: checked`.
 * When unchecking a legacy node that has `gmIncludeBusyTitles: true`, writing
 * `gmIncludeBusyDetails: false` ensures that the new key is explicitly stored on
 * the node, which overrides and takes precedence over the legacy key.
 */
export function setBusyDetailsChecked(
  checked: boolean,
  updateNodeData: (key: string, value: unknown) => void,
): void {
  updateNodeData(GOOGLE_MEET_BUSY_DETAILS_OPTION.key, checked);
}
