import { describe, expect, it } from "vitest";

import { appendChatContext, type ChatContextItem } from "@/lib/chatContext";
import {
  editableMessage,
  editedMessageContent,
  messagesBeforeEdit,
  withoutAttachmentBlock,
} from "@/lib/chatMessageEdit";

const WORKFLOW_ID = "9f1c2b7e-0d4a-4c1e-9b7a-1a2b3c4d5e6f";
const workflowItem: ChatContextItem = {
  kind: "workflow",
  workflowId: WORKFLOW_ID,
  workflowName: "Lead details",
};
const DRIVE_BLOCK =
  "\n\n[ATTACHED DRIVE FILE: report.pdf · id 0b8c2a8e-7d55-4e8e-9f3c-2b1d6f3a9c10]\n" +
  "The file is in Heym Drive; its content is not in this message.";

describe("withoutAttachmentBlock", () => {
  it("drops the Drive file block the server appended", () => {
    expect(withoutAttachmentBlock(`Summarise this${DRIVE_BLOCK}`)).toBe("Summarise this");
  });

  it("drops an inline file with its content", () => {
    expect(withoutAttachmentBlock("Read it\n\n[ATTACHED FILE: notes.txt]\nline one")).toBe(
      "Read it",
    );
  });

  it("leaves a message without an attachment unchanged", () => {
    expect(withoutAttachmentBlock("Plain question")).toBe("Plain question");
  });
});

describe("editableMessage", () => {
  it("returns the visible text and the context chips", () => {
    const stored = `${appendChatContext("Why is it slow?", [workflowItem])}${DRIVE_BLOCK}`;
    expect(editableMessage(stored)).toEqual({ text: "Why is it slow?", items: [workflowItem] });
  });
});

describe("editedMessageContent", () => {
  it("keeps the original context chips and leaves the attachment to the server", () => {
    const stored = `${appendChatContext("Why is it slow?", [workflowItem])}${DRIVE_BLOCK}`;
    expect(editedMessageContent(stored, "  Why is it failing?  ")).toBe(
      appendChatContext("Why is it failing?", [workflowItem]),
    );
  });

  it("sends just the text when the message had no context", () => {
    expect(editedMessageContent("Hello", "Hello there")).toBe("Hello there");
  });
});

describe("messagesBeforeEdit", () => {
  const messages = [
    { id: "1", role: "user" },
    { id: "2", role: "assistant" },
    { id: "3", role: "user" },
    { id: "4", role: "assistant" },
  ];

  it("keeps everything before the edited message", () => {
    expect(messagesBeforeEdit(messages, "3")).toEqual(messages.slice(0, 2));
  });

  it("keeps nothing when the first message is edited", () => {
    expect(messagesBeforeEdit(messages, "1")).toEqual([]);
  });

  it("refuses an assistant message or an unknown id", () => {
    expect(messagesBeforeEdit(messages, "2")).toBeNull();
    expect(messagesBeforeEdit(messages, "missing")).toBeNull();
  });
});
