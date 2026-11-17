import type { ReleaseEntry } from "@/features/release-tour/releaseTour.types";

/**
 * Source of truth for release notes and the tour that announces them.
 *
 * Adding a feature: append a section, list its id in `sectionOrder`, give it
 * `tour` metadata with a unique `tourVisual` key, and register a matching
 * visual component in `tourVisuals.ts`. Keep `tourEnabled: false` while the
 * release is still in progress, then flip it on in the release commit.
 *
 * No revision to bump: the stored id is derived from the slide ids, so changing
 * `sectionOrder` re-marks the release unseen and the tour reopens on its own.
 *
 * The registry keeps only the five most recently published sections. When a sixth
 * arrives, drop the oldest one along with its visual component and its registration
 * in `tourVisuals.ts`, and trim any release entry left without sections.
 */
export const RELEASE_REGISTRY: ReleaseEntry[] = [
  {
    releaseId: "2026.37",
    publishedAt: new Date("2026-11-19T12:00:00Z"),
    headline: "Gmail Send and Outlook Send",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Send email from Gmail and Outlook accounts, without an SMTP password.",
      tourEnabled: true,
      sectionOrder: ["mail-send"],
    },
    sections: [{
      id: "mail-send", title: "Gmail Send and Outlook Send",
      publishedAt: new Date("2026-11-19T12:00:00Z"),
      blocks: [{ type: "prose", markdown: "Two new nodes send email from the accounts your triggers already read. **Gmail Send** uses a **Gmail (OAuth2)** credential and **Outlook Send** an **Outlook Mail (OAuth2)** credential, so no App Password or SMTP server is needed. Both have every **Send Email** field: To, Cc and Bcc, Subject, a text or HTML Body, and Drive attachments, all with expressions, the expression dialog and agent tool fields. **From** sends as one of the account's addresses, such as a Gmail Send mail as alias or an Outlook shared mailbox; the account's own addresses show as chips under the field. The sent email lands in the account's Sent folder. Outlook credentials connected before this release need one **Reconnect** to allow sending; the node shows a reminder until then. In Heym Work, a flow's **Email sending** connection now lists Gmail and Outlook accounts next to SMTP." }],
      tour: {
        description: "Send from a Gmail or Outlook account with the same fields as Send Email, plus From, and no SMTP password.",
        useCases: ["Answer each support email from the inbox it arrived in", "Send a quote with a Drive PDF from your Microsoft 365 mailbox", "Reply as support@ through a Gmail Send mail as alias"],
        tourVisual: "mail-send",
        docTarget: { categoryId: "nodes", slug: "gmail-send-node", title: "Gmail Send" },
      },
    }],
  },

  {
    releaseId: "2026.36",
    publishedAt: new Date("2026-11-18T12:00:00Z"),
    headline: "Outlook Calendar",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Find free time in Outlook and Microsoft 365 calendars and send Teams invitations.",
      tourEnabled: true,
      sectionOrder: ["outlook-calendar"],
    },
    sections: [{
      id: "outlook-calendar", title: "Outlook Calendar",
      publishedAt: new Date("2026-11-18T12:00:00Z"),
      blocks: [{ type: "prose", markdown: "The new **Outlook Calendar** node brings everything the Google Meet node does to Outlook.com and Microsoft 365 work or school calendars, connected with an **Outlook Calendar (OAuth2)** credential through Microsoft Graph. **Read Available Time Slots** returns the free time between your Busy, Tentative and Away events, recurring meetings and all-day events included, in any time zone and up to 60 days ahead. Enter a colleague's email address to read their free/busy the way Outlook's Scheduling Assistant does, or a calendar name such as **Work** to read one of your other calendars. **Create Meeting** sends Outlook invitations with a Microsoft Teams link; **Update** and **Delete** notify the guests. Every field accepts expressions and can be filled by an Agent, so an agent can find a time and book it in one conversation." }],
      tour: {
        description: "Read free time in Outlook or Microsoft 365 calendars, yours or a colleague's, and send invitations with Teams links.",
        useCases: ["Let visitors book a Teams call in your free time", "Have an agent find a slot that suits you and a colleague", "Reschedule or cancel meetings and notify every guest"],
        tourVisual: "outlook-calendar",
        docTarget: { categoryId: "nodes", slug: "outlook-calendar-node", title: "Outlook Calendar" },
      },
    }],
  },

  {
    releaseId: "2026.35",
    publishedAt: new Date("2026-11-17T12:00:00Z"),
    headline: "Outlook Trigger",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Start workflows from Outlook and Microsoft 365 mail, including email you flag.",
      tourEnabled: true,
      sectionOrder: ["outlook-trigger"],
    },
    sections: [{
      id: "outlook-trigger", title: "Outlook Trigger",
      publishedAt: new Date("2026-11-17T12:00:00Z"),
      blocks: [{ type: "prose", markdown: "The new **Outlook Trigger** starts a run for each new email in an Outlook.com or Microsoft 365 work or school mailbox, connected with an **Outlook Mail (OAuth2)** credential through Microsoft Graph instead of a password. Watch the inbox, the **Focused** or **Other** inbox, high-importance mail, Sent Items, all received mail, or one of your folders. Turn on **Flagged email only** and flagging an email starts its run at the next poll, older email included. List addresses under **Only email sent to** to react only to an alias or a plus address. Once the run starts, Heym can mark the email read, move it to Archive or move it to Deleted Items; the default leaves it alone. The output matches the IMAP and Gmail Triggers, with the Outlook message id, conversation id, folder, categories and a link to the email added, and **Download attachments to Drive** works the same way." }],
      tour: {
        description: "Start a run for each new Outlook or Microsoft 365 email, or for each email you flag, then mark it read, archive it or delete it.",
        useCases: ["Turn every flagged email into a follow-up task", "Triage the Focused Inbox and mark each email read once it is handled", "Read invoice PDFs from a folder an Outlook rule fills and archive them"],
        tourVisual: "outlook-trigger",
        docTarget: { categoryId: "nodes", slug: "outlook-trigger-node", title: "Outlook Trigger" },
      },
    }],
  },

  {
    releaseId: "2026.34",
    publishedAt: new Date("2026-11-16T12:00:00Z"),
    headline: "Gmail Trigger",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Start workflows from Gmail by tab, label or alias, and tidy each email after its run.",
      tourEnabled: true,
      sectionOrder: ["gmail-trigger"],
    },
    sections: [{
      id: "gmail-trigger", title: "Gmail Trigger",
      publishedAt: new Date("2026-11-16T12:00:00Z"),
      blocks: [{ type: "prose", markdown: "The new **Gmail Trigger** starts a run for each new email in a Gmail or Google Workspace account, connected with a **Gmail (OAuth2)** credential instead of an app password. Watch the inbox, one tab such as **Primary** or **Promotions**, Important, Starred, Sent, all received mail, or one of your labels. List addresses under **Only email sent to** to react only to a Send mail as alias, a plus address or a Workspace alias. Once the run starts, Heym can mark the email read, archive it or move it to Trash; the default leaves it alone. The output matches the IMAP Trigger, with the Gmail message id, thread id and labels added, and **Download attachments to Drive** works the same way." }],
      tour: {
        description: "Start a run for each new Gmail email, by tab, label or alias, then mark it read, archive it or move it to Trash.",
        useCases: ["Triage the Primary tab and mark each email read once it is handled", "Read invoice PDFs from a Gmail label and archive them", "React only to mail sent to sales@ or a plus address"],
        tourVisual: "gmail-trigger",
        docTarget: { categoryId: "nodes", slug: "gmail-trigger-node", title: "Gmail Trigger" },
      },
    }],
  },

  {
    releaseId: "2026.33",
    publishedAt: new Date("2026-11-15T00:00:00Z"),
    headline: "Standardized /mcp server endpoints",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Connect new MCP clients through /mcp, with existing /sse servers preserved.",
      tourEnabled: true,
      sectionOrder: ["mcp-endpoint"],
    },
    sections: [
      {
        id: "mcp-endpoint", title: "Standardized /mcp endpoint for new MCP servers",
        publishedAt: new Date("2026-11-15T00:00:00Z"),
        blocks: [{ type: "prose", markdown: "New MCP servers get an address ending in `/mcp`. Servers you already have keep their `/sse` address, so connected clients keep working. Copy JSON and Add to Cursor always use the right address." }],
        tour: {
          description: "New MCP servers get an address ending in /mcp. Servers you already have keep their /sse address, so connected clients keep working. Copy JSON and Add to Cursor always use the right address.",
          useCases: ["Connect MCP clients to /api/mcp", "Create named servers with the new /mcp route", "Keep existing /sse clients and Cursor integrations working as before"],
          tourVisual: "mcp-endpoint",
          docTarget: { categoryId: "tabs", slug: "mcp-tab", title: "MCP / A2A" },
        },
      },
    ],
  },
];
