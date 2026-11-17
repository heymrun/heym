import { describe, expect, it } from "vitest";

import {
  EMAIL_SEND_NODE_LABELS,
  emailSendHasFromField,
  isEmailSendNodeType,
  mailAccountProvider,
} from "./emailSendNodes";

describe("emailSendNodes", () => {
  it("knows the three email senders and nothing else", () => {
    for (const type of ["sendEmail", "gmailSend", "outlookSend"]) {
      expect(isEmailSendNodeType(type)).toBe(true);
    }
    for (const type of ["gmailTrigger", "outlookTrigger", "slack", "", null, undefined]) {
      expect(isEmailSendNodeType(type)).toBe(false);
    }
  });

  it("gives Gmail Send and Outlook Send a From field, not SMTP", () => {
    expect(emailSendHasFromField("sendEmail")).toBe(false);
    expect(emailSendHasFromField("gmailSend")).toBe(true);
    expect(emailSendHasFromField("outlookSend")).toBe(true);
  });

  it("names each sender in validation messages", () => {
    expect(EMAIL_SEND_NODE_LABELS).toEqual({
      sendEmail: "Send Email",
      gmailSend: "Gmail Send",
      outlookSend: "Outlook Send",
    });
  });

  it("names the account each sender reads", () => {
    expect(mailAccountProvider("gmailSend")).toBe("gmail");
    expect(mailAccountProvider("outlookSend")).toBe("outlook");
    expect(mailAccountProvider("sendEmail")).toBeNull();
  });
});
