import { computed, reactive, type ComputedRef, type Ref } from "vue";

import type {
  CollabIdentity,
  CollabPermission,
  CursorPoint,
  MirroredAssistantMessage,
  PresenceState,
} from "@/features/collab/types";
import { collabColor } from "@/features/collab/colors";

const PEER_TTL_MS = 60_000;
const CURSOR_IDLE_MS = 10_000;

export interface CollabPeer {
  identity: CollabIdentity;
  state: PresenceState | null;
  lastSeen: number;
  /** `clickAt` marks the latest click, so each one replays the ripple. */
  cursor: (CursorPoint & { at: number; clickAt: number | null }) | null;
  assistantMessages: MirroredAssistantMessage[] | null;
}

export interface CollabUser {
  userId: string;
  name: string;
  color: string;
  permission: CollabPermission;
  sids: string[];
  isSelf: boolean;
  mic: boolean;
}

export interface RemoteCursor extends CursorPoint {
  clickAt: number | null;
  sid: string;
  userId: string;
  name: string;
  color: string;
}

export interface Presence {
  /** Other sessions in the room, by session id. This tab is not in it. */
  peers: Map<string, CollabPeer>;
  users: ComputedRef<CollabUser[]>;
  cursors: ComputedRef<RemoteCursor[]>;
  hasPeers: ComputedRef<boolean>;
  hasWriter: ComputedRef<boolean>;
  onJoin(identity: CollabIdentity): void;
  onPresence(identity: CollabIdentity, state: PresenceState): void;
  onCursor(identity: CollabIdentity, point: CursorPoint | null, click?: boolean): void;
  onAssistant(identity: CollabIdentity, messages: MirroredAssistantMessage[]): void;
  onLeave(sid: string): void;
  /** Drops silent peers and idle cursors; returns the dropped session ids. */
  expire(now?: number): string[];
  latestSidOf(userId: string): string | null;
  clear(): void;
}

export function createPresence(me: Ref<CollabIdentity | null>, selfMic: Ref<boolean>): Presence {
  const peers: Map<string, CollabPeer> = reactive(new Map<string, CollabPeer>());

  function touch(identity: CollabIdentity): CollabPeer {
    const existing = peers.get(identity.sid);
    if (existing) {
      existing.identity = identity;
      existing.lastSeen = Date.now();
      return existing;
    }
    peers.set(identity.sid, {
      identity,
      state: null,
      lastSeen: Date.now(),
      cursor: null,
      assistantMessages: null,
    });
    return peers.get(identity.sid) as CollabPeer;
  }

  function onJoin(identity: CollabIdentity): void {
    touch(identity);
  }

  function onPresence(identity: CollabIdentity, state: PresenceState): void {
    touch(identity).state = state;
  }

  function onCursor(identity: CollabIdentity, point: CursorPoint | null, click = false): void {
    const peer = touch(identity);
    const now = Date.now();
    peer.cursor = point
      ? { ...point, at: now, clickAt: click ? now : (peer.cursor?.clickAt ?? null) }
      : null;
  }

  function onAssistant(identity: CollabIdentity, messages: MirroredAssistantMessage[]): void {
    touch(identity).assistantMessages = messages;
  }

  function onLeave(sid: string): void {
    peers.delete(sid);
  }

  function expire(now = Date.now()): string[] {
    const removed: string[] = [];
    for (const [sid, peer] of [...peers.entries()]) {
      if (now - peer.lastSeen > PEER_TTL_MS) {
        peers.delete(sid);
        removed.push(sid);
      } else if (peer.cursor && now - peer.cursor.at > CURSOR_IDLE_MS) {
        peer.cursor = null;
      }
    }
    return removed;
  }

  function latestSidOf(userId: string): string | null {
    let latest: CollabPeer | null = null;
    for (const peer of peers.values()) {
      if (peer.identity.userId !== userId) continue;
      if (!latest || peer.lastSeen > latest.lastSeen) latest = peer;
    }
    return latest ? latest.identity.sid : null;
  }

  function clear(): void {
    peers.clear();
  }

  const users = computed<CollabUser[]>(() => {
    const byUser = new Map<string, CollabUser>();
    const self = me.value;
    if (self) {
      byUser.set(self.userId, {
        userId: self.userId,
        name: self.name,
        color: collabColor(self.userId),
        permission: self.permission,
        sids: [self.sid],
        isSelf: true,
        mic: selfMic.value,
      });
    }
    for (const peer of peers.values()) {
      const { identity } = peer;
      const known = byUser.get(identity.userId);
      if (known) {
        known.sids.push(identity.sid);
        if (identity.permission === "write") known.permission = "write";
        known.mic = known.mic || Boolean(peer.state?.mic);
        continue;
      }
      byUser.set(identity.userId, {
        userId: identity.userId,
        name: identity.name,
        color: collabColor(identity.userId),
        permission: identity.permission,
        sids: [identity.sid],
        isSelf: false,
        mic: Boolean(peer.state?.mic),
      });
    }
    return [...byUser.values()];
  });

  const cursors = computed<RemoteCursor[]>(() =>
    [...peers.values()].flatMap((peer) =>
      peer.cursor
        ? [
            {
              sid: peer.identity.sid,
              userId: peer.identity.userId,
              name: peer.identity.name,
              color: collabColor(peer.identity.userId),
              region: peer.cursor.region,
              anchor: peer.cursor.anchor,
              x: peer.cursor.x,
              y: peer.cursor.y,
              key: peer.cursor.key ?? null,
              hint: peer.cursor.hint ?? null,
              on: peer.cursor.on ?? null,
              node: peer.cursor.node ?? null,
              clickAt: peer.cursor.clickAt,
            },
          ]
        : [],
    ),
  );

  const hasPeers = computed<boolean>(() => peers.size > 0);
  const hasWriter = computed<boolean>(() =>
    [...peers.values()].some((peer) => peer.identity.permission === "write"),
  );

  return {
    peers,
    users,
    cursors,
    hasPeers,
    hasWriter,
    onJoin,
    onPresence,
    onCursor,
    onAssistant,
    onLeave,
    expire,
    latestSidOf,
    clear,
  };
}
