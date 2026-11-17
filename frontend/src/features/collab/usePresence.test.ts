import { ref } from "vue";
import { describe, expect, it } from "vitest";

import type { CollabIdentity, CursorPoint } from "@/features/collab/types";
import { createPresence } from "@/features/collab/usePresence";

describe("createPresence", () => {
  it.each(["canvas", "header"] as const)("hides same-account cursors in the %s region", (region) => {
    const local: CollabIdentity = { sid: "first", userId: "me", name: "Me", permission: "write" };
    const otherTab = { ...local, sid: "second" };
    const collaborator = { ...local, sid: "third", userId: "other", name: "Other" };
    const point: CursorPoint = { region, anchor: "start", x: 10, y: 20 };

    for (const [self, sibling] of [[local, otherTab], [otherTab, local]] as const) {
      const presence = createPresence(ref(self), ref(false));
      presence.onCursor(sibling, point);
      presence.onCursor(collaborator, point);

      expect(presence.cursors.value.map(({ sid }) => sid)).toEqual([collaborator.sid]);
      expect(presence.users.value.filter(({ isSelf }) => isSelf)).toMatchObject([
        { userId: self.userId, sids: [self.sid, sibling.sid] },
      ]);
    }
  });
});
