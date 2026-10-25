import {
  computed,
  inject,
  onBeforeUnmount,
  provide,
  ref,
  watch,
  type ComputedRef,
  type InjectionKey,
  type Ref,
} from "vue";
import { useEventListener, useThrottleFn } from "@vueuse/core";

import type {
  CollabIdentity,
  CursorPoint,
  MetaDraft,
  FlowViewport,
  FollowState,
  MirroredAssistantMessage,
  RunInputs,
  ServerMessage,
} from "@/features/collab/types";
import type { CollabUser, RemoteCursor } from "@/features/collab/usePresence";
import type { DragPosition, LiveSync } from "@/features/collab/useLiveSync";
import { onDismissOverlays } from "@/composables/useOverlayBackHandler";
import { CollabClient, collabSocketUrl, type CollabStatus } from "@/features/collab/collabClient";
import {
  followedTranscript,
  followerCount,
  localFollowSignals,
} from "@/features/collab/followSignals";
import { collabColor } from "@/features/collab/colors";
import { pointAt } from "@/features/collab/regions";
import { anchorElement, anchorOffset, hoverHint } from "@/features/collab/uiReplay";
import { useUiMirror } from "@/features/collab/useUiMirror";
import { setToastFilter, useToast } from "@/composables/useToast";
import { setRequestGuard } from "@/services/api";
import { createFollow } from "@/features/collab/useFollow";
import { createLiveSync } from "@/features/collab/useLiveSync";
import { createPresence } from "@/features/collab/usePresence";
import { createVoice } from "@/features/collab/useVoice";
import { useWorkflowStore } from "@/stores/workflow";

const HEARTBEAT_MS = 20_000;
// Requests a following tab may still send: session refresh and read-only expression previews.
const SPECTATOR_ALLOWED_WRITES = ["/auth/", "/expressions/"];
const MODIFIER_KEYS = new Set(["Shift", "Control", "Alt", "Meta", "Escape"]);
const UNAVAILABLE_MESSAGE =
  "Live collaboration is unavailable right now, so cursors, live edits, follow and voice are off. The editor works as usual.";
// Said once per page load, however many workflows are opened after it.
let unavailableToastShown = false;
const EXPIRY_CHECK_MS = 5_000;
const PRESENCE_THROTTLE_MS = 100;
const CURSOR_THROTTLE_MS = 66;

export interface CollabUserView extends CollabUser {
  speaking: boolean;
  audioFailed: boolean;
  following: boolean;
}

export interface CollabContext {
  me: Ref<CollabIdentity | null>;
  status: Ref<CollabStatus>;
  users: ComputedRef<CollabUserView[]>;
  cursors: ComputedRef<RemoteCursor[]>;
  followedUser: ComputedRef<CollabUserView | null>;
  toggleFollow(userId: string): void;
  stopFollowing(): void;
  micOn: Ref<boolean>;
  micError: Ref<string | null>;
  autoplayBlocked: Ref<boolean>;
  toggleMic(): Promise<void>;
  resumeAudio(): void;
  reportViewport(viewport: FlowViewport): void;
  reportCursor(point: CursorPoint | null): void;
  /** Sent at once, not throttled, so the ripple lands where the click happened. */
  reportClick(point: CursorPoint): void;
  setViewportApplier(apply: ((viewport: FlowViewport) => void) | null): void;
  sendDragPositions(positions: DragPosition[]): void;
  /** Sends this tab's AI Assistant transcript to the people following it. */
  sendAssistantTranscript(messages: MirroredAssistantMessage[]): void;
  /** The workflow name or description a collaborator is typing, in their color. */
  peerMeta: ComputedRef<PeerMetaDraft | null>;
  setMetaDraft(meta: MetaDraft | null): void;
}

export interface PeerMetaDraft extends MetaDraft {
  color: string;
}

export const COLLAB_CONTEXT: InjectionKey<CollabContext> = Symbol("canvas-collab");

export function useCollabContext(): CollabContext | null {
  return inject(COLLAB_CONTEXT, null);
}

/** Joins the canvas room of `workflowId` while it is set and provides the context below. */
export function useCanvasCollab(workflowId: Ref<string | null>): CollabContext {
  const store = useWorkflowStore();
  const me = ref<CollabIdentity | null>(null);
  const status = ref<CollabStatus>("closed");
  const micOn = ref(false);
  const localViewport = ref<FlowViewport | null>(null);
  const localMeta = ref<MetaDraft | null>(null);
  const presence = createPresence(me, micOn);
  let client: CollabClient | null = null;
  let liveSync: LiveSync | null = null;
  let joinedAt = 0;
  let viewportApplier: ((viewport: FlowViewport) => void) | null = null;
  let timers: Array<ReturnType<typeof setInterval>> = [];

  const voice = createVoice({
    me,
    micOn,
    sendSignal: (to, data) => client?.send({ t: "signal", to, data }),
    peerSids: () => [...presence.peers.keys()],
  });
  const follow = createFollow({
    store,
    presence,
    applyViewport: (viewport) => viewportApplier?.(viewport),
  });

  // A streamed canvas run reports its history id only while it runs; keep it for followers.
  const lastRunId = ref<string | null>(null);
  watch(
    () => [store.isExecuting, store.currentExecutionId] as const,
    ([executing, id]) => {
      if (executing && id) lastRunId.value = id;
    },
  );

  function shownExecutionId(): string | null {
    const result = store.executionResult;
    if (store.isExecuting || !result) return null;
    return result.execution_history_id ?? lastRunId.value;
  }

  // Run inputs can be large; they only travel while someone follows this tab.
  function runInputs(): RunInputs | null {
    if (followerCount.value === 0) return null;
    return {
      text: store.runInputText,
      values: store.runInputValues,
      json: store.runInputJson,
    };
  }

  function followState(): FollowState {
    return {
      viewport: localViewport.value,
      selectedNodeId: store.selectedNodeId,
      leftPanelOpen: localFollowSignals.leftPanelOpen,
      panelOpen: localFollowSignals.panelOpen,
      panelTab: store.propertiesPanelTab,
      expression: localFollowSignals.expression,
      debugOpen: localFollowSignals.debugOpen,
      historyOpen: localFollowSignals.historyOpen,
      historyExecutionId: localFollowSignals.historyExecutionId,
      runningExecutionId: store.isExecuting ? store.currentExecutionId : null,
      shownExecutionId: shownExecutionId(),
      dialogs: localFollowSignals.dialogs,
      assistant: localFollowSignals.assistant,
      runInputs: runInputs(),
    };
  }

  function sendPresence(): void {
    if (!client || !me.value) return;
    client.send({
      t: "presence",
      state: {
        follow: followState(),
        mic: micOn.value,
        dirty: store.hasUnsavedChanges,
        joinedAt,
        following: follow.followingSid.value,
        meta: localMeta.value,
      },
    });
  }

  const sendPresenceSoon = useThrottleFn(
    () => {
      if (presence.hasPeers.value) sendPresence();
    },
    PRESENCE_THROTTLE_MS,
    true,
  );
  watch(
    () => [
      followState(),
      micOn.value,
      store.hasUnsavedChanges,
      follow.followingSid.value,
      localMeta.value,
    ],
    () => {
      void sendPresenceSoon();
    },
    { deep: true },
  );

  const { showToast } = useToast();

  const sendCursor = useThrottleFn(
    (point: CursorPoint | null) => client?.send({ t: "cursor", point }),
    CURSOR_THROTTLE_MS,
    true,
  );

  // Who follows this tab; each newcomer is announced, so nobody is watched unknowingly.
  watch(
    () => [...presence.peers.values()]
      .filter((peer) => peer.state?.following === me.value?.sid)
      .map((peer) => peer.identity.sid)
      .join(","),
    (key, previousKey) => {
      const sids = key ? key.split(",") : [];
      const before = previousKey ? previousKey.split(",") : [];
      followerCount.value = sids.length;
      for (const sid of sids) {
        const follower = presence.peers.get(sid)?.identity;
        if (before.includes(sid) || !follower || follower.userId === me.value?.userId) continue;
        showToast(`${follower.name} is following you`, "info");
      }
    },
    { immediate: true },
  );

  // Pointers over panels and dialogs, placed on the element under them so they land right when
  // the two screens lay it out differently. The canvas reports its own, in flow coordinates.
  let pagePointer: { target: EventTarget | null; x: number; y: number } | null = null;
  let anchored: { node: EventTarget | null; found: ReturnType<typeof anchorElement> } = {
    node: null,
    found: null,
  };
  function pagePoint(target: EventTarget | null, x: number, y: number): CursorPoint | null {
    const point = pointAt(target, x, y);
    if (!point) return null;
    if (anchored.node !== target || !anchored.found?.element.isConnected) {
      anchored = { node: target, found: anchorElement(target) };
    }
    const hint = followerCount.value > 0 ? hoverHint(target) : null;
    return { ...point, on: anchorOffset(anchored.found, x, y), hint };
  }
  const flushPagePointer = useThrottleFn(
    () => {
      const pointer = pagePointer;
      const point = pointer ? pagePoint(pointer.target, pointer.x, pointer.y) : null;
      if (point) context.reportCursor(point);
    },
    CURSOR_THROTTLE_MS,
    true,
  );
  useEventListener(document, "pointermove", (event: PointerEvent) => {
    if (!presence.hasPeers.value) return;
    pagePointer = { target: event.target, x: event.clientX, y: event.clientY };
    void flushPagePointer();
  });
  useEventListener(document, "pointerdown", (event: PointerEvent) => {
    if (!presence.hasPeers.value) return;
    const point = pagePoint(event.target, event.clientX, event.clientY);
    if (point) context.reportClick(point);
  });

  // Clicks, typing, hover and scroll anywhere in the editor, for followers.
  const uiMirror = useUiMirror({
    send: (message) => client?.send(message),
    followerCount,
  });

  // A following tab is a spectator: its own click or keystroke takes control back, and until
  // then nothing it replays may write. Avatars and the follow label keep following.
  function endFollowOnOwnInput(event: Event): void {
    if (!event.isTrusted || !follow.followingSid.value) return;
    if (event instanceof KeyboardEvent && MODIFIER_KEYS.has(event.key)) return;
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest("[data-collab-keep-follow]")) return;
    follow.stop();
  }
  useEventListener(document, "pointerdown", endFollowOnOwnInput, { capture: true });
  useEventListener(document, "keydown", endFollowOnOwnInput, { capture: true });
  watch(
    () => follow.followingSid.value !== null,
    (spectating) => {
      if (!spectating) uiMirror.reset();
      setRequestGuard(
        spectating
          ? (config) => {
              const method = (config.method ?? "get").toLowerCase();
              if (method === "get" || method === "head") return null;
              const url = config.url ?? "";
              if (SPECTATOR_ALLOWED_WRITES.some((prefix) => url.startsWith(prefix))) return null;
              return "Paused while following someone";
            }
          : null,
      );
      setToastFilter(spectating ? (type) => type !== "error" : null);
    },
  );

  // The node under a followed pointer shows its hover buttons (Run, AI) here too.
  let hoverMarked: Element | null = null;
  watch(
    () => {
      const sid = follow.followingSid.value;
      const cursor = sid ? presence.peers.get(sid)?.cursor : null;
      return cursor?.region === "canvas" ? (cursor.node ?? null) : null;
    },
    (nodeId) => {
      hoverMarked?.removeAttribute("data-collab-hover");
      hoverMarked = nodeId
        ? document.querySelector(`.vue-flow__node[data-id="${CSS.escape(nodeId)}"]`)
        : null;
      hoverMarked?.setAttribute("data-collab-hover", "");
    },
  );

  // The transcript of whoever this tab follows, from the moment following starts.
  watch(
    () => follow.followingSid.value,
    (sid) => {
      followedTranscript.value = sid ? (presence.peers.get(sid)?.assistantMessages ?? []) : [];
    },
  );
  useEventListener(document.documentElement, "mouseleave", () => context.reportCursor(null));

  /** Unsaved changes belong to people who can save them. */
  function dropWriterlessDraft(): void {
    if (me.value?.permission !== "read" || !store.hasUnsavedChanges) return;
    if (presence.hasWriter.value) return;
    const id = store.currentWorkflow?.id;
    if (id) void store.loadWorkflow(id);
  }

  function onMessage(message: ServerMessage): void {
    if (message.t === "welcome") {
      me.value = {
        sid: message.sid,
        userId: message.userId,
        name: message.name,
        permission: message.permission,
      };
      if (!joinedAt) joinedAt = Date.now();
      presence.clear();
      voice.closeAll();
      sendPresence();
      liveSync?.begin();
      return;
    }
    if (!me.value) return;
    switch (message.t) {
      case "join":
        presence.onJoin(message.from);
        sendPresence();
        return;
      case "leave":
        presence.onLeave(message.from.sid);
        voice.closePeer(message.from.sid);
        dropWriterlessDraft();
        return;
      case "presence":
        presence.onPresence(message.from, message.state);
        voice.reconcile();
        return;
      case "cursor":
        presence.onCursor(message.from, message.point ?? null, message.click === true);
        return;
      case "assistant":
        presence.onAssistant(message.from, message.messages);
        if (message.from.sid === follow.followingSid.value) {
          followedTranscript.value = message.messages;
        }
        return;
      case "ui":
        if (message.from.sid === follow.followingSid.value) uiMirror.replay(message);
        return;
      case "signal":
        void voice.handleSignal(message.from.sid, message.data);
        return;
      case "resync":
        liveSync?.begin();
        return;
      case "error":
        return;
      default:
        liveSync?.handle(message);
    }
  }

  function reportUnavailable(): void {
    if (unavailableToastShown) return;
    unavailableToastShown = true;
    showToast(UNAVAILABLE_MESSAGE, "error", 6000);
  }

  function start(id: string): void {
    const session = new CollabClient({
      url: collabSocketUrl(id),
      onMessage,
      onStatus: (next) => {
        status.value = next;
      },
      onUnavailable: reportUnavailable,
    });
    const sync = createLiveSync({
      store,
      client: session,
      me,
      presence,
      isSpectating: () => follow.followingSid.value !== null,
    });
    client = session;
    liveSync = sync;
    store.setCollabHooks({
      saveHeaders: (kind) => sync.saveHeaders(kind),
      resolveConflict: (updatedAt) => sync.resolveConflict(updatedAt),
      announceReload: () => sync.announceReload(),
      isSpectating: () => follow.followingSid.value !== null,
    });
    session.start();
    timers = [
      setInterval(sendPresence, HEARTBEAT_MS),
      setInterval(() => {
        const removed = presence.expire();
        for (const sid of removed) voice.closePeer(sid);
        if (removed.length > 0) dropWriterlessDraft();
      }, EXPIRY_CHECK_MS),
    ];
  }

  function stop(): void {
    timers.forEach(clearInterval);
    timers = [];
    followerCount.value = 0;
    follow.stop();
    setRequestGuard(null);
    setToastFilter(null);
    voice.reset();
    liveSync?.stop();
    liveSync = null;
    client?.stop();
    client = null;
    store.setCollabHooks(null);
    presence.clear();
    me.value = null;
    joinedAt = 0;
    status.value = "closed";
  }

  watch(
    workflowId,
    (id) => {
      stop();
      if (!id) return;
      // Collaboration is extra: if it cannot start, the editor still opens without it.
      try {
        start(id);
      } catch {
        stop();
        reportUnavailable();
      }
    },
    { immediate: true },
  );
  onBeforeUnmount(stop);
  // Esc goes through the app's overlay handler, which closes open dialogs first.
  const stopDismissListener = onDismissOverlays(() => {
    if (follow.followingSid.value) follow.stop();
  });
  onBeforeUnmount(stopDismissListener);

  const users = computed<CollabUserView[]>(() =>
    presence.users.value.map((user) => ({
      ...user,
      speaking: user.sids.some((sid) => voice.speaking.has(sid)),
      audioFailed: !user.isSelf && user.sids.some((sid) => voice.failed.has(sid)),
      following:
        follow.followingSid.value !== null && user.sids.includes(follow.followingSid.value),
    })),
  );
  // Click ripples and tooltips belong to following: only the person followed shows them.
  const cursors = computed<RemoteCursor[]>(() =>
    presence.cursors.value.map((cursor) =>
      cursor.sid === follow.followingSid.value
        ? cursor
        : { ...cursor, clickAt: null, hint: null },
    ),
  );
  const peerMeta = computed<PeerMetaDraft | null>(() => {
    for (const peer of presence.peers.values()) {
      const meta = peer.state?.meta;
      if (meta && peer.identity.permission === "write") {
        return { ...meta, color: collabColor(peer.identity.userId) };
      }
    }
    return null;
  });
  const followedUser = computed<CollabUserView | null>(
    () => users.value.find((user) => user.following) ?? null,
  );

  const context: CollabContext = {
    me,
    status,
    users,
    cursors,
    followedUser,
    toggleFollow(userId: string): void {
      const user = users.value.find((candidate) => candidate.userId === userId);
      if (!user || user.isSelf) return;
      if (user.following) {
        follow.stop();
        return;
      }
      const sid = presence.latestSidOf(userId);
      if (sid) follow.start(sid);
    },
    stopFollowing: (): void => follow.stop(),
    micOn,
    micError: voice.micError,
    autoplayBlocked: voice.autoplayBlocked,
    toggleMic: (): Promise<void> => voice.toggleMic(),
    resumeAudio: (): void => voice.resumeAudio(),
    reportViewport(viewport: FlowViewport): void {
      localViewport.value = viewport;
    },
    reportCursor(point: CursorPoint | null): void {
      if (presence.hasPeers.value) void sendCursor(point);
    },
    reportClick(point: CursorPoint): void {
      if (followerCount.value > 0) client?.send({ t: "cursor", point, click: true });
    },
    setViewportApplier(apply: ((viewport: FlowViewport) => void) | null): void {
      viewportApplier = apply;
    },
    sendDragPositions(positions: DragPosition[]): void {
      liveSync?.sendDragPositions(positions);
    },
    sendAssistantTranscript(messages: MirroredAssistantMessage[]): void {
      if (followerCount.value > 0) client?.send({ t: "assistant", messages });
    },
    peerMeta,
    setMetaDraft(meta: MetaDraft | null): void {
      localMeta.value = meta;
    },
  };
  provide(COLLAB_CONTEXT, context);
  return context;
}
