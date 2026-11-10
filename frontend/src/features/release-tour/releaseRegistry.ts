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
    releaseId: "2026.30",
    publishedAt: new Date("2026-11-10T22:00:00Z"),
    headline: "Images, audio and any text file in vector stores",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Photos, recordings and scanned pages become searchable RAG sources.",
      tourEnabled: true,
      sectionOrder: ["rag-media-upload"],
    },
    sections: [{
      id: "rag-media-upload", title: "Images, audio and any text file in vector stores",
      publishedAt: new Date("2026-11-10T22:00:00Z"),
      blocks: [{ type: "prose", markdown: "Drop a photo, a screenshot, a voice note (WhatsApp's `.opus` files too) or a call recording on a vector store and it becomes searchable. Images are read with the Converter's OCR, and audio is transcribed on your own instance with the same Whisper model, in the background, so a long recording does not hold the upload open. PDF pages without a text layer are now read with OCR instead of being skipped, and a plain-text file of any name, such as `notes` or `README`, goes in as text. Heym Work's Knowledge pages take the same files." }],
      tour: {
        description: "Put photos, recordings, scanned PDFs and plain-text files of any name into a vector store.",
        useCases: ["Search call recordings from a RAG node", "Make photographed receipts and whiteboards searchable", "Index scanned contracts without a separate OCR step"],
        tourVisual: "rag-media-upload",
        docTarget: { categoryId: "tabs", slug: "vectorstores-tab", title: "Vectorstores" },
      },
    }],
  },

  {
    releaseId: "2026.29",
    publishedAt: new Date("2026-11-10T16:00:00Z"),
    headline: "Rerank RAG search results with a Decision Model",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "The best answer first, scored by the model you already use for decisions.",
      tourEnabled: true,
      sectionOrder: ["decision-reranker"],
    },
    sections: [{
      id: "decision-reranker", title: "Rerank search results with a Decision Model",
      publishedAt: new Date("2026-11-10T16:00:00Z"),
      blocks: [{ type: "prose", markdown: "Turn on **Enable Reranker** in a **RAG** search and the **Reranker Credential** list now offers your **Decision Model** credentials next to Cohere. Enter the model, for example `jev-latest`, and the node sends the question with each finding in its own request, several at a time: the decision model scores how relevant that finding is to the question, and the results come back ordered by that score, with `relevance_score` from 0 to 1 on each one. A failed call fails the node with the reason, so a workflow never continues with results in the wrong order, and each rerank shows up in Traces as one entry with every finding's answer and the total token usage. Cohere reranking works as before." }],
      tour: {
        description: "Let a decision model score every search result against the question and put the best answer first.",
        useCases: ["Feed an Agent only the passages that answer the question", "Rerank support articles before drafting a reply", "Use one decision model for routing, judging and reranking"],
        tourVisual: "decision-reranker",
        docTarget: { categoryId: "nodes", slug: "rag-node", title: "RAG / Vector Store" },
      },
    }],
  },

  {
    releaseId: "2026.28",
    publishedAt: new Date("2026-11-10T12:00:00Z"),
    headline: "Transcribe voice notes and recordings in the Converter node",
    releaseTour: {
      label: "New in Heym", introTitle: "New in this release",
      introDescription: "Speech becomes text inside your workflow, on your own instance.",
      tourEnabled: true,
      sectionOrder: ["voice-transcribe"],
    },
    sections: [{
      id: "voice-transcribe", title: "Voice transcribe in the Converter node",
      publishedAt: new Date("2026-11-10T12:00:00Z"),
      blocks: [{ type: "prose", markdown: "Pick **Audio → Text (Voice Transcribe)** in a **Converter** node and point it at an mp3, wav or ogg file in Drive. The node returns what was said as text, together with the language it heard and timed segments. Recognition runs on your own Heym instance with one multilingual model that covers about a hundred languages and detects the spoken one, the same way on Docker and Kubernetes. Recordings can be up to 30 minutes long. Pass the transcript to an LLM or Agent node to summarize a call, route a voice note or fill in a ticket." }],
      tour: {
        description: "Turn a voice note or call recording into text inside a workflow, in any language, on your own instance.",
        useCases: ["Summarize a customer call recording with an LLM node", "Route an uploaded voice note to the right team", "Keep timed transcripts of meetings searchable"],
        tourVisual: "voice-transcribe",
        docTarget: { categoryId: "nodes", slug: "converter-node", title: "Converter" },
      },
    }],
  },

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
];
