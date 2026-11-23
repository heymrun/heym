import { describe, expect, it } from "vitest";

import { heymOperationOptions } from "@/components/Panels/propertiesPanel/operationOptions";
import { NODE_DEFINITIONS } from "@/types/node";

import {
  HEYM_CHAT_FIELD_KEYS,
  HEYM_CHAT_OPERATION,
  hasHeymQuestionOutput,
  heymChatExpressionFields,
  isHeymChatOperation,
} from "./heymOperations";

describe("Heym Send Chat Message operation", () => {
  it("is offered in the Heym operation picker", () => {
    expect(heymOperationOptions).toContainEqual({
      value: HEYM_CHAT_OPERATION,
      label: "Send Chat Message",
    });
  });

  it("only the chat operation counts as chat", () => {
    expect(isHeymChatOperation("sendChatMessage")).toBe(true);
    for (const operation of ["listWorkflows", "getBoard", "", undefined]) {
      expect(isHeymChatOperation(operation)).toBe(false);
    }
  });

  it("gives only a Heym node sending chat messages a QUESTION output", () => {
    expect(hasHeymQuestionOutput("heym", "sendChatMessage")).toBe(true);
    expect(hasHeymQuestionOutput("heym", "listWorkflows")).toBe(false);
    expect(hasHeymQuestionOutput("heym", undefined)).toBe(false);
    expect(hasHeymQuestionOutput("codex", "sendChatMessage")).toBe(false);
  });

  it("navigates the message, and the conversation id only while continuing", () => {
    expect(heymChatExpressionFields({}).map((field) => field.key)).toEqual(["heymChatMessage"]);
    expect(
      heymChatExpressionFields({ heymChatContinue: true }).map((field) => field.key),
    ).toEqual(["heymChatMessage", "heymChatConversationId"]);
  });

  it("lists every expression field as a chat field the panel can hand to an agent", () => {
    const keys = heymChatExpressionFields({ heymChatContinue: true }).map((field) => field.key);
    expect([...HEYM_CHAT_FIELD_KEYS].sort()).toEqual([...keys].sort());
  });

  it("starts with every switch off", () => {
    const defaults = NODE_DEFINITIONS.heym.defaultData;
    expect(defaults.heymChatMessage).toBe("");
    expect(defaults.heymChatNoHistory).toBe(false);
    expect(defaults.heymChatContinue).toBe(false);
    expect(defaults.heymChatConversationId).toBe("");
    expect(defaults.heymChatFireAndForget).toBe(false);
  });
});
