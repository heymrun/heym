import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

export type CollabPermission = "read" | "write";

/** Who sent a message. The server stamps it; a client cannot set it. */
export interface CollabIdentity {
  sid: string;
  userId: string;
  name: string;
  permission: CollabPermission;
}

/** Where a pointer is. Canvas points are flow coordinates; panel points are pixels. */
export type CursorRegion =
  | "canvas"
  | "header"
  | "left"
  | "right"
  | "bottom"
  | "assistant"
  | "analyzer"
  | "guide"
  | "dialog";

export interface CursorPoint {
  region: CursorRegion;
  /** Panels: which horizontal edge `x` is measured from, so buttons line up across widths. */
  anchor: "start" | "end";
  x: number;
  y: number;
  /** Dialogs: the dialog's title, so the pointer lands in the same dialog. */
  key?: string | null;
  /** The tooltip or title text under the pointer, shown beside it. */
  hint?: string | null;
  /** The element under the pointer, which places it right when the two layouts differ. */
  on?: CursorAnchor | null;
  /** Canvas: the node under the pointer, whose hover buttons a follower sees too. */
  node?: string | null;
}

export interface CursorAnchor {
  target: UiTarget;
  /** Where in the element, as shares of its width and height. */
  fx: number;
  fy: number;
}

/** An element in a dialog, panel or the page, named so another screen can find its copy. */
export interface UiTarget {
  /** "dialog:<title>", "region:<name>" or "page". */
  scope: string;
  tag: string;
  testid: string | null;
  label: string | null;
  text: string | null;
  icon: string | null;
  /** Hover only: a structural match for elements nothing else names. */
  classes: string | null;
  index: number;
}

export type UiAction =
  | { action: "click"; target: UiTarget }
  | { action: "input"; target: UiTarget; value: string }
  | { action: "hover"; target: UiTarget | null }
  | { action: "scroll"; target: UiTarget; top: number; left: number }
  | { action: "key"; target: UiTarget; key: string };

export interface MirroredAssistantMessage {
  id: string;
  role: "user" | "assistant";
  content: string;
}

/** The live part of a followed person's AI Assistant; the transcript travels separately. */
export interface AssistantMirror {
  open: boolean;
  mode: "agent" | "ask";
  draft: string;
}

export interface RunInputs {
  text: string;
  values: Record<string, string>;
  json: string;
}

export interface FlowViewport {
  x: number;
  y: number;
  zoom: number;
  width: number;
  height: number;
}

/** What a follower mirrors. Rendered with the follower's own data and permissions. */
export interface FollowState {
  viewport: FlowViewport | null;
  selectedNodeId: string | null;
  leftPanelOpen: boolean;
  panelOpen: boolean;
  panelTab: string | null;
  expression: { nodeId: string; field: string } | null;
  debugOpen: boolean;
  historyOpen: boolean;
  historyExecutionId: string | null;
  runningExecutionId: string | null;
  /** The finished run this person's Debug panel shows. */
  shownExecutionId: string | null;
  /** Editor dialogs and side panels this person has open, by name. */
  dialogs: string[];
  /** Sent only while someone follows this person. */
  assistant: AssistantMirror | null;
  runInputs: RunInputs | null;
}

export interface PresenceState {
  follow: FollowState;
  mic: boolean;
  dirty: boolean;
  joinedAt: number;
  /** The session this person follows, if any. */
  following: string | null;
  /** The workflow name or description they are typing, or have just saved. */
  meta?: MetaDraft | null;
}

export interface MetaDraft {
  name?: string;
  description?: string;
}

export type SyncOp =
  | { k: "node.put"; id: string; node: WorkflowNode }
  | { k: "node.pos"; id: string; x: number; y: number }
  | { k: "node.del"; id: string }
  | { k: "edge.put"; id: string; edge: WorkflowEdge }
  | { k: "edge.del"; id: string };

export interface SignalPayload {
  description?: RTCSessionDescriptionInit;
  candidate?: RTCIceCandidateInit;
}

export type ServerMessage =
  | ({ t: "welcome" } & CollabIdentity)
  | { t: "join"; from: CollabIdentity }
  | { t: "leave"; from: CollabIdentity }
  | { t: "presence"; from: CollabIdentity; state: PresenceState }
  | { t: "cursor"; from: CollabIdentity; point: CursorPoint | null; click?: boolean }
  | { t: "ops"; from: CollabIdentity; seq: number; ops: SyncOp[] }
  | { t: "sync_req"; from: CollabIdentity; to: string }
  | {
      t: "snapshot";
      from: CollabIdentity;
      to: string;
      nodes: WorkflowNode[];
      edges: WorkflowEdge[];
    }
  | { t: "reload"; from: CollabIdentity }
  | { t: "signal"; from: CollabIdentity; to: string; data: SignalPayload }
  | { t: "assistant"; from: CollabIdentity; messages: MirroredAssistantMessage[] }
  | ({ t: "ui"; from: CollabIdentity } & UiAction)
  | {
      t: "saved";
      updatedAt: string | null;
      sid: string | null;
      hash: string | null;
      byUserId: string;
    }
  | { t: "resync" }
  | { t: "error"; message: string };

export type ClientMessage =
  | { t: "presence"; state: PresenceState }
  | { t: "cursor"; point: CursorPoint | null; click?: boolean }
  | { t: "ops"; seq: number; ops: SyncOp[] }
  | { t: "sync_req"; to: string }
  | { t: "snapshot"; to: string; nodes: WorkflowNode[]; edges: WorkflowEdge[] }
  | { t: "reload" }
  | { t: "signal"; to: string; data: SignalPayload }
  | { t: "assistant"; messages: MirroredAssistantMessage[] }
  | ({ t: "ui" } & UiAction);
