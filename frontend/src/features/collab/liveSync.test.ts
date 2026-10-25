import { describe, expect, it } from "vitest";

import type { SyncOp } from "@/features/collab/types";
import type { WorkflowNode } from "@/types/workflow";
import {
  PendingKeys,
  applyOps,
  buildBaseline,
  mergeSnapshot,
  nodeDataKey,
  nodePosKey,
  rebaseHistory,
  revertToBaseline,
  stateHash,
  takeDiff,
  type SyncBaseline,
  type SyncGraph,
} from "@/features/collab/liveSync";

function node(id: string, label: string, x = 0, y = 0): WorkflowNode {
  return { id, type: "llm", position: { x, y }, data: { label } } as WorkflowNode;
}

function clone(graph: SyncGraph): SyncGraph {
  return JSON.parse(JSON.stringify(graph)) as SyncGraph;
}

function labels(graph: SyncGraph): string[] {
  return graph.nodes.map((item) => item.data.label);
}

interface SimMessage {
  from: string;
  seq: number;
  ops: SyncOp[];
}

/** One canvas in a simulated room. The log is the single order the server gives everyone. */
class SimCanvas {
  graph: SyncGraph;
  baseline: SyncBaseline;
  pending = new PendingKeys();
  seq = 0;

  constructor(
    readonly sid: string,
    start: SyncGraph,
  ) {
    this.graph = clone(start);
    this.baseline = buildBaseline(this.graph);
  }

  edit(change: (graph: SyncGraph) => void, log: SimMessage[]): void {
    change(this.graph);
    const ops = takeDiff(this.baseline, this.graph);
    this.seq += 1;
    this.pending.mark(ops, this.seq);
    log.push({ from: this.sid, seq: this.seq, ops });
  }

  receive(message: SimMessage): void {
    if (message.from === this.sid) {
      this.pending.ack(message.ops, message.seq);
      return;
    }
    this.graph = applyOps(this.graph, message.ops, (key) => this.pending.has(key), this.baseline);
  }
}

describe("takeDiff", () => {
  it("emits a put and a position for a new node, then only a position for a move", () => {
    const baseline = buildBaseline({ nodes: [], edges: [] });
    const graph: SyncGraph = { nodes: [node("a", "A", 10, 20)], edges: [] };

    expect(takeDiff(baseline, graph).map((op) => op.k)).toEqual(["node.put", "node.pos"]);
    graph.nodes[0] = { ...graph.nodes[0], position: { x: 30, y: 20 } };
    expect(takeDiff(baseline, graph)).toEqual([{ k: "node.pos", id: "a", x: 30, y: 20 }]);
    expect(takeDiff(baseline, graph)).toEqual([]);
  });

  it("emits a put for a data change and deletes for removed nodes and edges", () => {
    const graph: SyncGraph = {
      nodes: [node("a", "A"), node("b", "B")],
      edges: [{ id: "e1", source: "a", target: "b" }],
    };
    const baseline = buildBaseline(graph);

    graph.nodes[0].data.label = "A2";
    expect(takeDiff(baseline, graph).map((op) => op.k)).toEqual(["node.put"]);
    graph.nodes = [graph.nodes[0]];
    graph.edges = [];
    expect(takeDiff(baseline, graph)).toEqual([
      { k: "node.del", id: "b" },
      { k: "edge.del", id: "e1" },
    ]);
  });

  it("ignores runtime fields such as the run status", () => {
    const graph: SyncGraph = { nodes: [node("a", "A")], edges: [] };
    const baseline = buildBaseline(graph);

    graph.nodes[0] = { ...graph.nodes[0], data: { ...graph.nodes[0].data, status: "running" } };

    expect(takeDiff(baseline, graph)).toEqual([]);
  });
});

describe("applyOps", () => {
  it("keeps this canvas's run status when a peer changes the node", () => {
    const local: SyncGraph = { nodes: [node("a", "A")], edges: [] };
    local.nodes[0].data.status = "success";

    const next = applyOps(local, [{ k: "node.put", id: "a", node: node("a", "A2") }], () => false);

    expect(next.nodes[0].data.label).toBe("A2");
    expect(next.nodes[0].data.status).toBe("success");
  });

  it("creates a node where the peer placed it", () => {
    const next = applyOps(
      { nodes: [], edges: [] },
      [{ k: "node.put", id: "n", node: node("n", "N", 40, 50) }],
      () => false,
    );

    expect(next.nodes[0].position).toEqual({ x: 40, y: 50 });
  });

  it("drops a deleted node's edges and ignores an edge whose endpoint is gone", () => {
    const local: SyncGraph = {
      nodes: [node("a", "A"), node("b", "B")],
      edges: [{ id: "e1", source: "a", target: "b" }],
    };

    const next = applyOps(
      local,
      [
        { k: "node.del", id: "b" },
        { k: "edge.put", id: "e2", edge: { id: "e2", source: "a", target: "b" } },
      ],
      () => false,
    );

    expect(next.nodes.map((item) => item.id)).toEqual(["a"]);
    expect(next.edges).toEqual([]);
  });

  it("skips keys with unacknowledged local edits", () => {
    const local: SyncGraph = { nodes: [node("a", "mine")], edges: [] };

    const next = applyOps(
      local,
      [{ k: "node.put", id: "a", node: node("a", "theirs") }],
      (key) => key === nodeDataKey("a"),
    );

    expect(labels(next)).toEqual(["mine"]);
  });
});

describe("PendingKeys", () => {
  it("stays pending until the latest op for the key comes back", () => {
    const pending = new PendingKeys();
    const op: SyncOp = { k: "node.pos", id: "a", x: 1, y: 1 };

    pending.mark([op], 1);
    pending.mark([op], 2);
    pending.ack([op], 1);
    expect(pending.has(nodePosKey("a"))).toBe(true);
    pending.ack([op], 2);
    expect(pending.has(nodePosKey("a"))).toBe(false);
  });
});

describe("a simulated room", () => {
  const start: SyncGraph = { nodes: [node("a", "A")], edges: [] };

  it("converges on the later write in server order, either way round", () => {
    for (const order of [["x", "y"], ["y", "x"]]) {
      const x = new SimCanvas("x", start);
      const y = new SimCanvas("y", start);
      const sent: Record<string, SimMessage[]> = { x: [], y: [] };
      x.edit((graph) => {
        graph.nodes[0].data.label = "from x";
      }, sent.x);
      y.edit((graph) => {
        graph.nodes[0].data.label = "from y";
      }, sent.y);
      const log = order.flatMap((sid) => sent[sid]);

      for (const message of log) {
        x.receive(message);
        y.receive(message);
      }

      expect(labels(x.graph)).toEqual([`from ${order[1]}`]);
      expect(labels(y.graph)).toEqual([`from ${order[1]}`]);
    }
  });

  it("never jumps back a field someone is typing in", () => {
    const x = new SimCanvas("x", start);
    const y = new SimCanvas("y", start);
    const log: SimMessage[] = [];
    x.edit((graph) => {
      graph.nodes[0].data.label = "a";
    }, log);
    y.edit((graph) => {
      graph.nodes[0].data.label = "other";
    }, log);
    x.edit((graph) => {
      graph.nodes[0].data.label = "ab";
    }, log);

    for (const message of log) {
      x.receive(message);
      expect(labels(x.graph)).toEqual(["ab"]);
      y.receive(message);
    }

    expect(labels(y.graph)).toEqual(["ab"]);
  });

  it("keeps a move and a settings edit from overwriting each other", () => {
    const x = new SimCanvas("x", start);
    const y = new SimCanvas("y", start);
    const log: SimMessage[] = [];
    x.edit((graph) => {
      graph.nodes[0].position = { x: 90, y: 90 };
    }, log);
    y.edit((graph) => {
      graph.nodes[0].data.label = "renamed";
    }, log);

    for (const message of log) {
      x.receive(message);
      y.receive(message);
    }

    for (const canvas of [x, y]) {
      expect(canvas.graph.nodes[0].position).toEqual({ x: 90, y: 90 });
      expect(labels(canvas.graph)).toEqual(["renamed"]);
    }
  });

  it("brings a late joiner to the room's state with a snapshot and buffered ops", () => {
    const x = new SimCanvas("x", start);
    const y = new SimCanvas("y", start);
    const early: SimMessage[] = [];
    x.edit((graph) => {
      graph.nodes[0].data.label = "A1";
    }, early);
    for (const message of early) {
      x.receive(message);
      y.receive(message);
    }
    const z = new SimCanvas("z", start);
    const buffered: SimMessage[] = [];
    y.edit((graph) => {
      graph.nodes.push(node("n2", "B2", 50, 50));
    }, buffered);
    // x answers the sync request before y's op has reached it.
    const snapshot = clone(x.graph);
    for (const message of buffered) {
      x.receive(message);
      y.receive(message);
    }

    z.graph = mergeSnapshot(z.graph, snapshot, (key) => z.pending.has(key));
    z.baseline = buildBaseline(z.graph);
    for (const message of buffered) z.receive(message);

    expect(stateHash(z.graph)).toBe(stateHash(x.graph));
    expect(stateHash(y.graph)).toBe(stateHash(x.graph));
  });
});

describe("mergeSnapshot", () => {
  it("keeps local values for unacknowledged keys", () => {
    const local: SyncGraph = { nodes: [node("a", "mine", 5, 5), node("new", "N")], edges: [] };
    const snapshot: SyncGraph = {
      nodes: [node("a", "theirs", 9, 9), node("gone", "G")],
      edges: [],
    };
    const pending = new Set([nodeDataKey("a"), nodeDataKey("new"), nodeDataKey("gone")]);

    const merged = mergeSnapshot(local, snapshot, (key) => pending.has(key));

    expect(merged.nodes.map((item) => [item.id, item.data.label, item.position.x])).toEqual([
      ["a", "mine", 9],
      ["new", "N", 0],
    ]);
  });
});

describe("rebaseHistory", () => {
  it("lets undo revert only this canvas's own change", () => {
    const s0: SyncGraph = { nodes: [node("a", "A"), node("b", "B")], edges: [] };
    const s1 = clone(s0);
    s1.nodes[0].data.label = "A-mine";
    const remote: SyncOp[] = [{ k: "node.put", id: "b", node: node("b", "B-theirs") }];

    const [r0, r1] = rebaseHistory([clone(s0), s1], remote, () => false);

    expect(labels(r0)).toEqual(["A", "B-theirs"]);
    expect(labels(r1)).toEqual(["A-mine", "B-theirs"]);
  });
});

describe("stateHash", () => {
  it("ignores order and runtime fields and changes with content", () => {
    const one: SyncGraph = { nodes: [node("a", "A"), node("b", "B")], edges: [] };
    const two: SyncGraph = { nodes: [node("b", "B"), node("a", "A")], edges: [] };
    two.nodes[1].data.status = "error";

    expect(stateHash(two)).toBe(stateHash(one));
    one.nodes[0].data.label = "A2";
    expect(stateHash(one)).not.toBe(stateHash(two));
    expect(stateHash(one)).toMatch(/^[0-9a-z]{1,32}$/);
  });
});

describe("revertToBaseline", () => {
  it("undoes a local add, delete, move and edit while keeping run status", () => {
    const synced: SyncGraph = {
      nodes: [node("a", "A", 1, 2), node("b", "B")],
      edges: [{ id: "e1", source: "a", target: "b" }],
    };
    const baseline = buildBaseline(synced);
    const local = clone(synced);
    local.nodes[0].position = { x: 50, y: 60 };
    local.nodes[0].data.label = "changed";
    local.nodes[0].data.status = "success";
    local.nodes = [local.nodes[0], node("extra", "X")];
    local.edges = [];

    const reverted = revertToBaseline(baseline, local);

    expect(reverted).not.toBeNull();
    expect(stateHash(reverted as SyncGraph)).toBe(stateHash(synced));
    expect(reverted?.nodes[0].data.status).toBe("success");
  });

  it("returns null when nothing changed", () => {
    const synced: SyncGraph = { nodes: [node("a", "A")], edges: [] };

    expect(revertToBaseline(buildBaseline(synced), clone(synced))).toBeNull();
  });
});
