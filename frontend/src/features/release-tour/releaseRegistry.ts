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

  {
    releaseId: "2026.32",
    publishedAt: new Date("2026-11-14T21:00:00Z"),
    headline: "Email attachments in Heym Drive",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Work with the files an email brings, straight from the IMAP Trigger.",
      tourEnabled: true,
      sectionOrder: ["imap-attachments"],
    },
    sections: [{
      id: "imap-attachments", title: "Email attachments in Heym Drive",
      publishedAt: new Date("2026-11-14T21:00:00Z"),
      blocks: [{ type: "prose", markdown: "Turn on **Download attachments to Drive** in the IMAP Trigger and every attachment of a new email is saved to your Heym Drive while the run executes. The trigger output gets `attachments`, with each file's name, size and Drive link, and `file_ids`, which goes straight into an Agent's message, a Converter or a Drive node: read an invoice PDF, hand a contract to an Agent or pass a scan on. Up to 10 files per email are saved; a file over the Drive size limit is listed as skipped and the run keeps going. The email stays unread, and the toggle is off by default, so existing workflows behave as before." }],
      tour: {
        description: "Save the files of each new email to Drive and let the next node read them.",
        useCases: ["Extract totals and due dates from invoice PDFs sent to a billing inbox", "Hand contracts that arrive by email to an Agent for review", "File scans and delivery notes in Drive with the email they came with"],
        tourVisual: "imap-attachments",
        docTarget: { categoryId: "nodes", slug: "imap-trigger-node", title: "IMAP Trigger" },
      },
    }],
  },

  {
    releaseId: "2026.31",
    publishedAt: new Date("2026-11-14T12:00:00Z"),
    headline: "Revert a widget Chat changed",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Undo an AI change to a dashboard widget in one click.",
      tourEnabled: true,
      sectionOrder: ["chat-widget-revert"],
    },
    sections: [{
      id: "chat-widget-revert", title: "Revert a widget Chat changed",
      publishedAt: new Date("2026-11-14T12:00:00Z"),
      blocks: [{ type: "prose", markdown: "When Chat changes a dashboard widget, or you fine-tune one with AI, the card shows **Revert previous**. One click puts the widget back as it was before that change, together with any fix Chat made to its data in the same change: a change and its fixes are now one Edit History entry. The offer lasts until you reload or the widget changes again, and Heym never overwrites a save made since. Heym Work's pages offer the same button." }],
      tour: {
        description: "Undo the last AI change to a dashboard widget, from Chat or a fine-tune, in one click.",
        useCases: ["Try another chart from Chat and go back if the old one was better", "Undo a fine-tune that left a widget empty", "Review AI edits to a page before keeping them"],
        tourVisual: "chat-widget-revert",
        docTarget: { categoryId: "tabs", slug: "dashboard-tab", title: "Dashboard" },
      },
    }],
  },
];
