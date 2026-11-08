import { appendChatContext, extractChatContext, type ChatContextItem } from "@/lib/chatContext";

/**
 * Markers the server appends after a user message's text for its attachment
 * (`_build_user_message`). On an edit the server keeps that block itself, so the client
 * sends only the text and its own context.
 */
export const ATTACHMENT_MARKERS = [
  "\n\n[ATTACHED DRIVE FILE: ",
  "\n\n[ATTACHED FILE: ",
  "\n\n[ATTACHED IMAGE: ",
  "\n\n[ATTACHED ZIP: ",
] as const;

export interface EditableMessage {
  /** The text the user edits. */
  text: string;
  /** Context chips that stay with the message. */
  items: ChatContextItem[];
}

/** A stored user message without the attachment block the server appended to it. */
export function withoutAttachmentBlock(content: string): string {
  const positions = ATTACHMENT_MARKERS.map((marker) => content.indexOf(marker)).filter(
    (index) => index !== -1,
  );
  return positions.length > 0 ? content.slice(0, Math.min(...positions)) : content;
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
