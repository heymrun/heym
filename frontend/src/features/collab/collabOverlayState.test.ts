import { ref } from "vue";
import { describe, expect, it } from "vitest";

import type { CollabIdentity } from "@/features/collab/types";
import { computeCollabOverlayState } from "@/features/collab/collabOverlayState";
import { createPresence } from "@/features/collab/usePresence";

const userA: CollabIdentity = {
  sid: "sid-a-1",
  userId: "user-a",
  name: "Alice",
  permission: "write",
};

const userATab2: CollabIdentity = {
  sid: "sid-a-2",
  userId: "user-a",
  name: "Alice",
  permission: "write",
};

const userB: CollabIdentity = {
  sid: "sid-b-1",
  userId: "user-b",
  name: "Bob",
  permission: "read",
};

describe("computeCollabOverlayState", () => {
  it("hides the bar when alone on the workflow", () => {
    const me = ref<CollabIdentity | null>(userA);
    const presence = createPresence(me, ref(false));

    const state = computeCollabOverlayState({
      me: me.value,
      users: presence.users.value,
      status: "open",
    });

    expect(state.others).toEqual([]);
    expect(state.visible).toEqual([]);
    expect(state.showBar).toBe(false);
    expect(state.showReconnecting).toBe(false);
    expect(state.showOverlay).toBe(false);
  });

  it("hides the bar when the same user opens a second tab", () => {
    const me = ref<CollabIdentity | null>(userA);
    const presence = createPresence(me, ref(false));
    presence.onJoin(userATab2);

    // Presence keeps the self entry with both sessions merged, while the overlay omits it.
    expect(presence.users.value).toHaveLength(1);
    expect(presence.users.value[0]?.isSelf).toBe(true);
    expect(presence.users.value[0]?.sids).toEqual(["sid-a-1", "sid-a-2"]);

    const state = computeCollabOverlayState({
      me: me.value,
      users: presence.users.value,
      status: "open",
    });

    expect(state.others).toEqual([]);
    expect(state.showBar).toBe(false);
    expect(state.showOverlay).toBe(false);
  });

  it("shows only the other user when they join and hides the bar when they leave", () => {
    const me = ref<CollabIdentity | null>(userA);
    const presence = createPresence(me, ref(false));
    presence.onJoin(userATab2);
    presence.onJoin(userB);

    const joined = computeCollabOverlayState({
      me: me.value,
      users: presence.users.value,
      status: "open",
    });

    expect(joined.showOverlay).toBe(true);
    expect(joined.showBar).toBe(true);
    expect(joined.visible.map((u) => u.userId)).toEqual(["user-b"]);
    expect(joined.visible.every((u) => !u.isSelf)).toBe(true);

    presence.onLeave(userB.sid);

    const left = computeCollabOverlayState({
      me: me.value,
      users: presence.users.value,
      status: "open",
    });

    expect(left.others).toEqual([]);
    expect(left.showBar).toBe(false);
    expect(left.showOverlay).toBe(false);
  });

  it("keeps the Reconnecting notice visible alone when disconnected with nobody else present", () => {
    const me = ref<CollabIdentity | null>(userA);
    const presence = createPresence(me, ref(false));

    const state = computeCollabOverlayState({
      me: me.value,
      users: presence.users.value,
      status: "connecting",
    });

    expect(state.showOverlay).toBe(true);
    expect(state.showBar).toBe(false);
    expect(state.showReconnecting).toBe(true);
    expect(state.visible).toEqual([]);
  });

  it("caps visible avatars at maxVisible and counts only non-self overflow users", () => {
    const me = ref<CollabIdentity | null>(userA);
    const presence = createPresence(me, ref(false));
    for (let i = 1; i <= 7; i += 1) {
      presence.onJoin({
        sid: `sid-other-${i}`,
        userId: `user-${i}`,
        name: `User ${i}`,
        permission: "write",
      });
    }

    const state = computeCollabOverlayState({
      me: me.value,
      users: presence.users.value,
      status: "open",
    });

    expect(state.visible).toHaveLength(5);
    expect(state.hiddenCount).toBe(2);
    expect(state.visible.some((u) => u.userId === userA.userId)).toBe(false);
  });

  it("renders nothing before the current session identity is set", () => {
    const state = computeCollabOverlayState({
      me: null,
      users: [],
      status: "connecting",
    });

    expect(state.showOverlay).toBe(false);
    expect(state.showBar).toBe(false);
    expect(state.showReconnecting).toBe(false);
  });
});
