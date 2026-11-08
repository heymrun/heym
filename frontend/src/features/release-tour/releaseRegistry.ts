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
    releaseId: "2026.27",
    publishedAt: new Date("2026-11-08T12:00:00Z"),
    headline: "Two-factor sign-in, account deactivation and data retention",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Controls a security review asks for, on your own instance.",
      tourEnabled: true,
      sectionOrder: ["account-security"],
    },
    sections: [{
      id: "account-security", title: "Two-factor sign-in and offboarding",
      publishedAt: new Date("2026-11-08T12:00:00Z"),
      blocks: [{ type: "prose", markdown: "Turn on **two-factor sign-in** and every password sign-in asks for a code from an authenticator app. Anyone without one scans a QR code first, before reaching anything, and gets ten single-use recovery codes. SSO sign-in stays with your identity provider. Administrators get a **Users** tab in Settings: **Deactivate** an account when someone leaves and their sessions end, their keys stop working and the automatic triggers of their workflows pause; **Reactivate** brings it all back. Anyone can **Sign out other sessions** from Settings → Security. Execution history and LLM traces now keep 90 days by default, which you can change or turn off." }],
      tour: {
        description: "Require an authenticator code at password sign-in, offboard leavers in one click, and keep history for a set time.",
        useCases: ["Meet the MFA requirement of a security review", "Remove a departing employee's access and pause their automations", "Keep run history and prompts for 90 days only"],
        tourVisual: "account-security",
        docTarget: { categoryId: "reference", slug: "security", title: "Security" },
      },
    }],
  },

  {
    releaseId: "2026.26",
    publishedAt: new Date("2026-11-06T12:00:00Z"),
    headline: "Find free times and send Google Meet calendar invitations",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Turn your Google Calendar into a booking workflow.",
      tourEnabled: true,
      sectionOrder: ["google-meet"],
    },
    sections: [{
      id: "google-meet", title: "Book time with Google Meet",
      blocks: [{ type: "prose", markdown: "Connect a **Google Meet (OAuth2)** credential with Google login, then add a **Google Meet** node to read available calendar times or create, update and delete invitations. Reads default from now through the first day of next month; optional dates support shorter ranges or up to 60 days. Title, description, attendee emails, time zone and meeting times accept expressions and Agent autofill. For **Book a calendar with me**, show your free times, accept the visitor's selected time and email, and send the invitation from your connected account. The website includes **Available Time Slots** and **Book a Calendar with Me** templates." }],
      tour: {
        description: "Find available calendar times and send Meet invitations from your Google account.",
        useCases: ["Show when customers can book a call", "Invite a visitor using the email and time from your form", "Reschedule or cancel meetings and notify guests"],
        tourVisual: "google-meet",
        docTarget: { categoryId: "nodes", slug: "google-meet-node", title: "Google Meet" },
      },
    }],
  },

  {
    releaseId: "2026.25",
    publishedAt: new Date("2026-11-05T12:00:00Z"),
    headline: "Assign, prioritize and schedule board cards from Heym, Heym Work, Chat and MCP",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription: "Kanban boards become team task boards, managed the same way everywhere.",
      tourEnabled: true,
      sectionOrder: ["board-task-fields"],
    },
    sections: [{
      id: "board-task-fields",
      title: "Assign, prioritize and schedule board cards",
      publishedAt: new Date("2026-11-05T12:00:00Z"),
      blocks: [{
        type: "prose",
        markdown: "Open a card on the **Board** tab to give it an assignee, a priority, a due date and labels such as a client or project. The card shows them at a glance, and overdue work turns red. The order you drag cards into is kept, in Heym and in Heym Work. A board can also stop moving cards on its own: turn off **Advance cards automatically** in its settings for a plain team task board. Chat and any MCP client through `heym_chat` can now create and change boards, columns and cards, assign, move and comment on tasks, and list what is overdue or waiting for a review. Moving or commenting on a card never approves a review.",
      }],
      tour: {
        description: "Give cards an owner, a priority and a due date, and manage them from Heym, Heym Work, Chat or MCP.",
        useCases: ["See who works on which contract and what is overdue", "Ask Chat to move a task to Review and assign it to a colleague", "Keep a plain task board whose cards stay where people put them"],
        tourVisual: "board-task-fields",
        docTarget: { categoryId: "tabs", slug: "board-tab", title: "Board" },
      },
    }],
  },
  {
    releaseId: "2026.24",
    publishedAt: new Date("2026-10-30T12:00:00Z"),
    headline: "Open large files in a sandbox, plan schedules and map database relationships",
    releaseTour: {
      label: "New in Heym",
      introTitle: "New in this release",
      introDescription: "File analysis in a sandbox, Gantt schedules and entity relationships, in Heym and Heym Work.",
      tourEnabled: true,
      sectionOrder: ["file-analysis", "planning-widgets"],
    },
    sections: [{
      id: "file-analysis",
      title: "Open large files in an isolated sandbox",
      publishedAt: new Date("2026-10-31T12:00:00Z"),
      blocks: [{
        type: "prose",
        markdown: "Attach a PDF, spreadsheet, DOCX, CSV or JSON file in Chat, or name one in Drive. The file is stored in Drive and Chat opens it in an isolated Python sandbox with no network: it inspects the pages, sheets and columns first, then reads only the part your question needs, so a large file never fills the conversation. Follow-up questions reuse what was already read. Workflows that start with a File Upload trigger get the same ability: an Agent node that receives the uploaded file opens it the same way, with nothing to switch on, and a Code node reads it through **Files** with pandas, openpyxl, pdfplumber and python-docx.",
      }],
      tour: {
        description: "Ask about a large PDF or spreadsheet without pasting it. Chat inspects it in a sandbox and reads only what it needs.",
        useCases: ["Total a column on one sheet and add a value from the last page", "Summarize the risks in a 200-page contract", "Build a workflow that extracts the same fields from every uploaded invoice"],
        tourVisual: "file-analysis",
        docTarget: { categoryId: "reference", slug: "file-analysis", title: "File Analysis" },
      },
    }, {
      id: "planning-widgets",
      title: "Gantt schedules and database relationship diagrams",
      publishedAt: new Date("2026-10-30T12:00:00Z"),
      blocks: [{
        type: "prose",
        markdown: "Add a **Gantt** widget for tasks with start and end dates, completion percentages and dependencies. Choose **Entity relationships (DB)** to show tables, their fields, primary and foreign keys, and the relationships between them. Both types are available in Add widget and the Chart Output node. Heym Work can propose either view and draw a preview using the page’s own plan before you build it.",
      }],
      tour: {
        description: "See project schedules and database relationships on your dashboards and Work pages.",
        useCases: ["Track a delivery plan with task progress and dependencies", "Document a database with primary and foreign keys", "Preview a proposed timeline or schema in Heym Work"],
        tourVisual: "planning-widgets",
        docTarget: { categoryId: "nodes", slug: "chart-output-node", title: "Chart Output" },
      },
    }],
  },
];
