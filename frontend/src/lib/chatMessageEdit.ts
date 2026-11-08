import { splitAttachmentBlocks } from "@/lib/chatAttachment";
import { appendChatContext, extractChatContext, type ChatContextItem } from "@/lib/chatContext";

export interface EditableMessage {
  /** The text the user edits. */
  text: string;
  /** Context chips that stay with the message. */
  items: ChatContextItem[];
}

/**
 * A stored user message without the attachment blocks the server appended to it. On an edit
 * the server keeps those blocks itself, so the client sends only the text and its own context.
 */
export function withoutAttachmentBlock(content: string): string {
  return splitAttachmentBlocks(content).text;
}

/** The text a user edits, and the context chips that stay with it. */
export function editableMessage(content: string): EditableMessage {
  const { text, items } = extractChatContext(withoutAttachmentBlock(content));
  return { text, items };
}

/** The content an edit sends: the new text with the original message's context chips. */
export function editedMessageContent(original: string, text: string): string {
  return appendChatContext(text.trim(), editableMessage(original).items);
}

/**
 * The messages an edit keeps: everything before the edited message. Null when the id is not
 * one of the conversation's user messages.
 */
export function messagesBeforeEdit<T extends { id: string; role: string }>(
  messages: readonly T[],
  messageId: string,
): T[] | null {
  const index = messages.findIndex((message) => message.id === messageId);
  if (index === -1 || messages[index].role !== "user") return null;
  return messages.slice(0, index);
}
