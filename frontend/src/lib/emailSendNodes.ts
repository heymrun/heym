/** The nodes that send an email: SMTP, a Gmail account, or an Outlook mailbox. */
export const EMAIL_SEND_NODE_TYPES = ["sendEmail", "gmailSend", "outlookSend"] as const;

export type EmailSendNodeType = (typeof EMAIL_SEND_NODE_TYPES)[number];

/** The names validation messages use for each email node. */
export const EMAIL_SEND_NODE_LABELS: Record<EmailSendNodeType, string> = {
  sendEmail: "Send Email",
  gmailSend: "Gmail Send",
  outlookSend: "Outlook Send",
};

/** The account-backed senders, which read their From address from the account. */
export type MailAccountProvider = "gmail" | "outlook";

export function isEmailSendNodeType(type: string | null | undefined): type is EmailSendNodeType {
  return (EMAIL_SEND_NODE_TYPES as readonly string[]).includes(type ?? "");
}

/** Gmail Send and Outlook Send can send as another address of the account (From). */
export function emailSendHasFromField(type: string | null | undefined): boolean {
  return mailAccountProvider(type) !== null;
}

/** Which account a node sends from, or null for SMTP and every other node. */
export function mailAccountProvider(type: string | null | undefined): MailAccountProvider | null {
  if (type === "gmailSend") return "gmail";
  if (type === "outlookSend") return "outlook";
  return null;
}
