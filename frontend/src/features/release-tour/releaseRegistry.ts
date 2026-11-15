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
];
