import { describe, expect, it } from "vitest";

import type { NodeTemplate } from "@/features/templates/types/template.types";
import { buildWorkflowNodeFromNodeTemplate } from "@/lib/nodeFromTemplate";

describe("buildWorkflowNodeFromNodeTemplate", () => {
  it("hydrates gmIncludeBusyDetails from boolean value", () => {
    const node = buildWorkflowNodeFromNodeTemplate(
      {
        id: "tpl-1",
        name: "Meet",
        node_type: "googleMeet",
        node_data: { gmOperation: "read", gmIncludeBusyDetails: true },
      } as unknown as NodeTemplate,
      { x: 0, y: 0 },
      null,
    );
    expect(node.data.gmIncludeBusyDetails).toBe(true);
  });

  it("hydrates gmIncludeBusyDetails from legacy gmIncludeBusyTitles", () => {
    const node = buildWorkflowNodeFromNodeTemplate(
      {
        id: "tpl-2",
        name: "Meet",
        node_type: "googleMeet",
        node_data: { gmOperation: "read", gmIncludeBusyTitles: true },
      } as unknown as NodeTemplate,
      { x: 0, y: 0 },
      null,
    );
    expect(node.data.gmIncludeBusyDetails).toBe(true);
  });

  it("prioritizes explicit gmIncludeBusyDetails over legacy gmIncludeBusyTitles", () => {
    const nodeWithFalse = buildWorkflowNodeFromNodeTemplate(
      {
        id: "tpl-3",
        name: "Meet",
        node_type: "googleMeet",
        node_data: {
          gmOperation: "read",
          gmIncludeBusyDetails: false,
          gmIncludeBusyTitles: true,
        },
      } as unknown as NodeTemplate,
      { x: 0, y: 0 },
      null,
    );
    expect(nodeWithFalse.data.gmIncludeBusyDetails).toBe(false);

    const nodeWithNull = buildWorkflowNodeFromNodeTemplate(
      {
        id: "tpl-4",
        name: "Meet",
        node_type: "googleMeet",
        node_data: {
          gmOperation: "read",
          gmIncludeBusyDetails: null,
          gmIncludeBusyTitles: true,
        },
      } as unknown as NodeTemplate,
      { x: 0, y: 0 },
      null,
    );
    expect(nodeWithNull.data.gmIncludeBusyDetails).toBe(false);
  });

  it("migrates agentProvidedFields legacy gmIncludeBusyTitles to gmIncludeBusyDetails", () => {
    const node = buildWorkflowNodeFromNodeTemplate(
      {
        id: "tpl-5",
        name: "Meet",
        node_type: "googleMeet",
        node_data: {
          gmOperation: "read",
          agentProvidedFields: ["gmIncludeBusyTitles", "gmCalendarId"],
        },
      } as unknown as NodeTemplate,
      { x: 0, y: 0 },
      null,
    );
    expect(node.data.agentProvidedFields).toEqual(["gmIncludeBusyDetails", "gmCalendarId"]);
  });
});
