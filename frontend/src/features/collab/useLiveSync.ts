import { watch, type Ref } from "vue";

import type { CollabIdentity, ServerMessage, SyncOp } from "@/features/collab/types";
import type { CollabClient } from "@/features/collab/collabClient";
import type { Presence } from "@/features/collab/usePresence";
import type { useWorkflowStore } from "@/stores/workflow";
import {
  PendingKeys,
  applyOps,
  buildBaseline,
  mergeSnapshot,
  plainEdge,
  rebaseHistory,
  revertToBaseline,
  stateHash,
  syncedNode,
  takeDiff,
  type SyncBaseline,
  type SyncGraph,
} from "@/features/collab/liveSync";

const DIFF_INTERVAL_MS = 80;
const DRAG_INTERVAL_MS = 66;
const JOIN_SETTLE_MS = 700;
const SNAPSHOT_TIMEOUT_MS = 3000;
const PEER_SAVE_WAIT_MS = 1000;
const PEER_SAVE_POLL_MS = 100;
const REMEMBERED_PEER_SAVES = 10;

type WorkflowStore = ReturnType<typeof useWorkflowStore>;
type OpsMessage = Extract<ServerMessage, { t: "ops" }>;
type SnapshotMessage = Extract<ServerMessage, { t: "snapshot" }>;
type SavedMessage = Extract<ServerMessage, { t: "saved" }>;

export interface DragPosition {
  id: string;
  x: number;
  y: number;
}

export interface LiveSync {
  /** Catch up with the room: after (re)connecting or a server `resync`. */
  begin(): void;
  handle(message: ServerMessage): void;
  saveHeaders(kind: "graph" | "metadata"): Record<string, string>;
  resolveConflict(updatedAt: string | null): Promise<boolean>;
  announceReload(): void;
  sendDragPositions(positions: DragPosition[]): void;
  stop(): void;
}

export interface LiveSyncDeps {
  store: WorkflowStore;
  client: CollabClient;
  me: Ref<CollabIdentity | null>;
  presence: Presence;
  /** While following someone, changes replayed here are theirs and must not be sent again. */
  isSpectating: () => boolean;
}

/** The API formats UTC as `Z` and the 409 detail as `+00:00`; compare them as one. */
function sameRevision(a: string, b: string): boolean {
  return a.replace(/Z$/, "+00:00") === b.replace(/Z$/, "+00:00");
}

export function createLiveSync({
  store,
  client,
  me,
  presence,
  isSpectating,
}: LiveSyncDeps): LiveSync {
  const pending = new PendingKeys();
  const isPending = (key: string): boolean => pending.has(key);
  const peerSaves: string[] = [];
  let baseline: SyncBaseline = buildBaseline(graph());
  let seq = 0;
  let phase: "joining" | "live" = "live";
  let buffered: OpsMessage[] = [];
  let candidates: string[] = [];
  let diffTimer: ReturnType<typeof setTimeout> | null = null;
  let joinTimer: ReturnType<typeof setTimeout> | null = null;
  let lastDragAt = 0;

  function graph(): SyncGraph {
    return { nodes: store.nodes, edges: store.edges };
  }

  function canSend(): boolean {
    return me.value?.permission === "write" && presence.hasPeers.value && !isSpectating();
  }

  function sendOps(ops: SyncOp[]): void {
    seq += 1;
    pending.mark(ops, seq);
    client.send({ t: "ops", seq, ops }, true);
  }

  /** Sends local edits now. Alone on the canvas the baseline still advances, nothing is sent. */
  function flushLocal(): void {
    if (diffTimer) {
      clearTimeout(diffTimer);
      diffTimer = null;
    }
    if (isSpectating()) {
      const reverted = revertToBaseline(baseline, graph());
      if (reverted) store.revertLocalGraph(reverted.nodes, reverted.edges);
      return;
    }
    const ops = takeDiff(baseline, graph());
    if (ops.length > 0 && canSend()) sendOps(ops);
  }

  function applyRemote(ops: SyncOp[]): void {
    // Unsent local keystrokes become pending first, so a remote op cannot overwrite them.
    flushLocal();
    const next = applyOps(graph(), ops, isPending, baseline);
    store.applyRemoteGraph(next.nodes, next.edges, (states) =>
      rebaseHistory(states, ops, isPending),
    );
  }

  function clearJoin(): void {
    if (joinTimer) {
      clearTimeout(joinTimer);
      joinTimer = null;
    }
  }

  function goLive(): void {
    clearJoin();
    phase = "live";
    const replay = buffered;
    buffered = [];
    for (const message of replay) applyRemote(message.ops);
    client.flushQueue();
  }

  function requestNextSnapshot(): void {
    const target = candidates.shift();
    if (!target) {
      goLive();
      return;
    }
    client.send({ t: "sync_req", to: target });
    joinTimer = setTimeout(requestNextSnapshot, SNAPSHOT_TIMEOUT_MS);
  }

  function begin(): void {
    clearJoin();
    phase = "joining";
    buffered = [];
    // Presence replies to our join tell us who holds an unsaved draft.
    joinTimer = setTimeout(() => {
      candidates = [...presence.peers.values()]
        .filter((peer) => peer.identity.permission === "write" && peer.state?.dirty)
        .sort((a, b) => (a.state?.joinedAt ?? 0) - (b.state?.joinedAt ?? 0))
        .map((peer) => peer.identity.sid);
      requestNextSnapshot();
    }, JOIN_SETTLE_MS);
  }

  function onOps(message: OpsMessage): void {
    if (message.from.sid === me.value?.sid) {
      pending.ack(message.ops, message.seq);
      return;
    }
    if (phase === "joining") {
      buffered.push(message);
      return;
    }
    applyRemote(message.ops);
  }

  function onSnapshot(message: SnapshotMessage): void {
    if (phase !== "joining" || message.from.permission !== "write") return;
    const merged = mergeSnapshot(
      graph(),
      { nodes: message.nodes, edges: message.edges },
      isPending,
    );
    store.replaceGraphFromPeer(merged.nodes, merged.edges);
    baseline = buildBaseline(merged);
    goLive();
  }

  function onSyncRequest(from: CollabIdentity): void {
    if (me.value?.permission !== "write") return;
    flushLocal();
    client.send({
      t: "snapshot",
      to: from.sid,
      nodes: store.nodes.map(syncedNode),
      edges: store.edges.map(plainEdge),
    });
  }

  async function reloadSaved(): Promise<void> {
    const id = store.currentWorkflow?.id;
    if (id) await store.loadWorkflow(id);
  }

  function onSaved(message: SavedMessage): void {
    if (message.sid && message.sid === me.value?.sid) return;
    if (message.sid && presence.peers.has(message.sid)) {
      if (message.updatedAt) {
        peerSaves.push(message.updatedAt);
        if (peerSaves.length > REMEMBERED_PEER_SAVES) peerSaves.shift();
      }
      const matches = message.hash === null ? null : message.hash === stateHash(graph());
      store.adoptPeerSave(message.updatedAt, matches);
      void store.refreshWorkflowSettings();
      return;
    }
    if (!store.hasUnsavedChanges) {
      void reloadSaved();
      return;
    }
    if (me.value?.permission === "write") store.openExternalSaveConflict(message.updatedAt);
  }

  function handle(message: ServerMessage): void {
    switch (message.t) {
      case "ops":
        onOps(message);
        return;
      case "snapshot":
        onSnapshot(message);
        return;
      case "sync_req":
        onSyncRequest(message.from);
        return;
      case "reload":
        if (message.from.sid !== me.value?.sid) void reloadSaved();
        return;
      case "saved":
        onSaved(message);
        return;
      default:
        return;
    }
  }

  async function resolveConflict(updatedAt: string | null): Promise<boolean> {
    if (!updatedAt) return false;
    const deadline = Date.now() + PEER_SAVE_WAIT_MS;
    for (;;) {
      if (peerSaves.some((seen) => sameRevision(seen, updatedAt))) return true;
      if (Date.now() >= deadline) return false;
      await new Promise((resolve) => setTimeout(resolve, PEER_SAVE_POLL_MS));
    }
  }

  function saveHeaders(kind: "graph" | "metadata"): Record<string, string> {
    const self = me.value;
    if (!self) return {};
    flushLocal();
    const headers: Record<string, string> = { "X-Heym-Collab-Session": self.sid };
    if (kind === "graph") headers["X-Heym-Collab-Hash"] = stateHash(graph());
    return headers;
  }

  /** Positions while dragging; the store only learns the position on drag stop. */
  function sendDragPositions(positions: DragPosition[]): void {
    const now = Date.now();
    if (positions.length === 0 || !canSend() || now - lastDragAt < DRAG_INTERVAL_MS) return;
    lastDragAt = now;
    sendOps(
      positions.map((item): SyncOp => ({ k: "node.pos", id: item.id, x: item.x, y: item.y })),
    );
  }

  const stopGraphWatch = watch(
    () => [store.nodes, store.edges],
    () => {
      if (!diffTimer) diffTimer = setTimeout(flushLocal, DIFF_INTERVAL_MS);
    },
    { deep: true },
  );
  const stopLoadWatch = watch(
    () => store.graphLoadSeq,
    () => {
      baseline = buildBaseline(graph());
      pending.clear();
    },
  );

  function stop(): void {
    stopGraphWatch();
    stopLoadWatch();
    clearJoin();
    if (diffTimer) clearTimeout(diffTimer);
    diffTimer = null;
  }

  return {
    begin,
    handle,
    saveHeaders,
    resolveConflict,
    announceReload: (): void => client.send({ t: "reload" }),
    sendDragPositions,
    stop,
  };
}
