import type { OperationOptionGroup } from "../operationOptions";

export type SlackFieldKey =
  | "slackChannel"
  | "slackUser"
  | "slackThreadTs"
  | "slackMessageTs"
  | "message"
  | "slackFormTitle"
  | "slackSubmitLabel"
  | "slackOutcomeTitle"
  | "slackEmoji"
  | "slackLimit"
  | "slackAllowedUsers";

/** One expression field of a Slack operation, in the order the panel shows it. */
export interface SlackFieldSpec {
  key: SlackFieldKey;
  label: string;
  placeholder: string;
  hint?: string;
  rows?: number;
}

export const SLACK_DEFAULT_OPERATION = "sendMessage";
export const SLACK_WAITING_OPERATIONS: ReadonlySet<string> = new Set([
  "requestApproval",
  "sendButtons",
  "sendForm",
]);

export const slackOperationGroups: OperationOptionGroup[] = [
  {
    label: "Messages",
    options: [
      { value: "sendMessage", label: "Send channel message" },
      { value: "sendDirectMessage", label: "Send DM" },
      { value: "replyInThread", label: "Reply in thread" },
      { value: "updateMessage", label: "Update message" },
      { value: "postOutcome", label: "Post final outcome" },
    ],
  },
  {
    label: "Ask people (the run waits for the answer)",
    options: [
      { value: "requestApproval", label: "Request approval" },
      { value: "sendButtons", label: "Send message with buttons" },
      { value: "sendForm", label: "Send form" },
    ],
  },
  {
    label: "More",
    options: [
      { value: "addReaction", label: "Add reaction" },
      { value: "deleteMessage", label: "Delete message" },
      { value: "getMessages", label: "Read messages" },
      { value: "findUser", label: "Find person" },
    ],
  },
];

export const slackOutcomeOptions = [
  { value: "success", label: "Success" },
  { value: "failure", label: "Failure" },
  { value: "warning", label: "Warning" },
  { value: "info", label: "Info" },
];

const CHANNEL: SlackFieldSpec = {
  key: "slackChannel",
  label: "Channel or person",
  placeholder: "#general, C0123…, U0123… or name@company.com",
  hint: "A person's id or email posts in their direct messages.",
};
const USER: SlackFieldSpec = {
  key: "slackUser",
  label: "Person",
  placeholder: "U0123… or name@company.com",
};
const THREAD: SlackFieldSpec = {
  key: "slackThreadTs",
  label: "Thread",
  placeholder: "$announce.threadTs",
  hint: "Optional. The threadTs of an earlier Slack step keeps the conversation in one thread.",
};
const MESSAGE_TS: SlackFieldSpec = {
  key: "slackMessageTs",
  label: "Message",
  placeholder: "$announce.ts",
  hint: "The ts of the message an earlier Slack step posted.",
};
const MESSAGE: SlackFieldSpec = {
  key: "message",
  label: "Message",
  placeholder: "$input.text",
  hint: "Slack formatting works: *bold*, _italic_, <@U0123>, links.",
  rows: 3,
};
const ALLOWED: SlackFieldSpec = {
  key: "slackAllowedUsers",
  label: "Who can answer",
  placeholder: "Anyone in the channel",
  hint: "Optional. Comma separated user ids or emails.",
};

/** The expression fields an operation needs, in panel order. */
export function slackFieldsFor(operation: string): SlackFieldSpec[] {
  switch (operation) {
    case "sendDirectMessage":
      return [USER, MESSAGE];
    case "replyInThread":
      return [CHANNEL, { ...THREAD, hint: "The threadTs of the message to reply to." }, MESSAGE];
    case "updateMessage":
      return [CHANNEL, MESSAGE_TS, { ...MESSAGE, label: "New text" }];
    case "postOutcome":
      return [
        CHANNEL,
        THREAD,
        { key: "slackOutcomeTitle", label: "Title", placeholder: "Refund approved" },
        { ...MESSAGE, label: "Details" },
      ];
    case "requestApproval":
      return [CHANNEL, THREAD, { ...MESSAGE, label: "What needs approval" }, ALLOWED];
    case "sendButtons":
      return [CHANNEL, THREAD, MESSAGE, ALLOWED];
    case "sendForm":
      return [
        CHANNEL,
        THREAD,
        MESSAGE,
        { key: "slackFormTitle", label: "Form title", placeholder: "Incident details" },
        { key: "slackSubmitLabel", label: "Submit button", placeholder: "Submit" },
        ALLOWED,
      ];
    case "addReaction":
      return [
        CHANNEL,
        MESSAGE_TS,
        { key: "slackEmoji", label: "Emoji", placeholder: "white_check_mark" },
      ];
    case "deleteMessage":
      return [CHANNEL, MESSAGE_TS];
    case "getMessages":
      return [
        CHANNEL,
        { ...THREAD, hint: "Optional. Reads the thread's replies instead of the channel." },
        { key: "slackLimit", label: "How many", placeholder: "20" },
      ];
    case "findUser":
      return [USER];
    default:
      return [CHANNEL, THREAD, MESSAGE];
  }
}

/** Where Slack sends clicks for a credential, on this Heym. */
export function slackInteractionsPath(credentialId: string): string {
  return `/api/slack/interactions/${credentialId}`;
}
