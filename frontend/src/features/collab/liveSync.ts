import type { SyncOp } from "@/features/collab/types";
import type { WorkflowEdge, WorkflowNode } from "@/types/workflow";

/**
 * Pure live-editing rules (Figma's method for properties): every canvas applies ops in the
 * server's order, and ignores an op for a key it has an unacknowledged edit for until that
 * edit comes back. Node data and node position are separate keys.
 */

/** Node data a run writes while it is shown; each canvas keeps its own. */
export const RUNTIME_NODE_DATA_KEYS = [
  "status",
  "retryAttempt",
  "batchRuntimeStatus",
  "batchRuntimeRawStatus",
  "batchRuntimeRequestCounts",
  "__runbookEntrance",
] as const;

export interface SyncGraph {
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
}

/** The last value of each key this canvas sent or received. */
export interface SyncBaseline {
  data: Map<string, string>;
  pos: Map<string, string>;
  edges: Map<string, string>;
}

export type PendingCheck = (key: string) => boolean;

type NodeData = WorkflowNode["data"];

export function nodeDataKey(id: string): string {
  return `node:${id}:data`;
}

export function nodePosKey(id: string): string {
  return `node:${id}:pos`;
}

export function edgeKey(id: string): string {
  return `edge:${id}`;
}

export function opKey(op: SyncOp): string {
  switch (op.k) {
    case "node.pos":
      return nodePosKey(op.id);
    case "node.put":
    case "node.del":
      return nodeDataKey(op.id);
    default:
      return edgeKey(op.id);
  }
}

export function stableStringify(value: unknown): string {
  if (value === null || typeof value !== "object") return JSON.stringify(value) ?? "null";
  if (Array.isArray(value)) {
    return `[${value.map((item) => (item === undefined ? "null" : stableStringify(item))).join(",")}]`;
  }
  const record = value as Record<string, unknown>;
  const keys = Object.keys(record)
    .filter((key) => record[key] !== undefined)
    .sort();
  return `{${keys.map((key) => `${JSON.stringify(key)}:${stableStringify(record[key])}`).join(",")}}`;
}

export function stripRuntimeData(data: NodeData): NodeData {
  const copy = { ...data } as unknown as Record<string, unknown>;
  for (const key of RUNTIME_NODE_DATA_KEYS) delete copy[key];
  return copy as unknown as NodeData;
}

function runtimeData(data: NodeData | undefined): Partial<NodeData> {
  if (!data) return {};
  const source = data as unknown as Record<string, unknown>;
  const runtime: Record<string, unknown> = {};
  for (const key of RUNTIME_NODE_DATA_KEYS) {
    if (source[key] !== undefined) runtime[key] = source[key];
  }
  return runtime as Partial<NodeData>;
}

export function plainEdge(edge: WorkflowEdge): WorkflowEdge {
  const plain: WorkflowEdge = { id: edge.id, source: edge.source, target: edge.target };
  if (edge.sourceHandle) plain.sourceHandle = edge.sourceHandle;
  if (edge.targetHandle) plain.targetHandle = edge.targetHandle;
  return plain;
}

/** The node as other canvases receive it: no runtime fields, plain JSON. */
export function syncedNode(node: WorkflowNode): WorkflowNode {
  return JSON.parse(
    JSON.stringify({
      id: node.id,
      type: node.type,
      position: node.position,
      data: stripRuntimeData(node.data),
    }),
  ) as WorkflowNode;
}

function dataValue(node: WorkflowNode): string {
  return stableStringify({ type: node.type, data: stripRuntimeData(node.data) });
}

function posValue(position: { x: number; y: number }): string {
  return `${position.x},${position.y}`;
}

function edgeValue(edge: WorkflowEdge): string {
  return stableStringify(plainEdge(edge));
}

export function buildBaseline(graph: SyncGraph): SyncBaseline {
  const baseline: SyncBaseline = { data: new Map(), pos: new Map(), edges: new Map() };
  for (const node of graph.nodes) {
    baseline.data.set(node.id, dataValue(node));
    baseline.pos.set(node.id, posValue(node.position));
  }
  for (const edge of graph.edges) baseline.edges.set(edge.id, edgeValue(edge));
  return baseline;
}

/** Ops that turn the baseline into `graph`. Updates the baseline to match. */
export function takeDiff(baseline: SyncBaseline, graph: SyncGraph): SyncOp[] {
  const ops: SyncOp[] = [];
  const nodeIds = new Set<string>();
  for (const node of graph.nodes) {
    nodeIds.add(node.id);
    const data = dataValue(node);
    if (baseline.data.get(node.id) !== data) {
      baseline.data.set(node.id, data);
      ops.push({ k: "node.put", id: node.id, node: syncedNode(node) });
    }
    const pos = posValue(node.position);
    if (baseline.pos.get(node.id) !== pos) {
      baseline.pos.set(node.id, pos);
      ops.push({ k: "node.pos", id: node.id, x: node.position.x, y: node.position.y });
    }
  }
  for (const id of [...baseline.data.keys()]) {
    if (nodeIds.has(id)) continue;
    baseline.data.delete(id);
    baseline.pos.delete(id);
    ops.push({ k: "node.del", id });
  }
  const edgeIds = new Set<string>();
  for (const edge of graph.edges) {
    edgeIds.add(edge.id);
    const value = edgeValue(edge);
    if (baseline.edges.get(edge.id) !== value) {
      baseline.edges.set(edge.id, value);
      ops.push({ k: "edge.put", id: edge.id, edge: plainEdge(edge) });
    }
  }
  for (const id of [...baseline.edges.keys()]) {
    if (edgeIds.has(id)) continue;
    baseline.edges.delete(id);
    ops.push({ k: "edge.del", id });
  }
  return ops;
}

/** Keys with an edit this canvas sent that has not come back from the server yet. */
export class PendingKeys {
  private readonly latest = new Map<string, number>();

  mark(ops: SyncOp[], seq: number): void {
    for (const op of ops) this.latest.set(opKey(op), seq);
  }

  ack(ops: SyncOp[], seq: number): void {
    for (const op of ops) {
      const key = opKey(op);
      const latest = this.latest.get(key);
      if (latest !== undefined && latest <= seq) this.latest.delete(key);
    }
  }

  has(key: string): boolean {
    return this.latest.has(key);
  }

  clear(): void {
    this.latest.clear();
  }
}

/** Applies remote ops, skipping pending keys. Updates `baseline` so they are not sent back. */
export function applyOps(
  graph: SyncGraph,
  ops: SyncOp[],
  isPending: PendingCheck,
  baseline?: SyncBaseline,
): SyncGraph {
  let nodes = [...graph.nodes];
  let edges = [...graph.edges];
  for (const op of ops) {
    if (isPending(opKey(op))) continue;
    switch (op.k) {
      case "node.put": {
        const index = nodes.findIndex((item) => item.id === op.id);
        const next: WorkflowNode =
          index >= 0
            ? {
                ...nodes[index],
                type: op.node.type,
                data: { ...op.node.data, ...runtimeData(nodes[index].data) },
              }
            : {
                id: op.id,
                type: op.node.type,
                position: { ...op.node.position },
                data: { ...op.node.data },
              };
        if (index >= 0) {
          nodes[index] = next;
        } else {
          nodes.push(next);
          baseline?.pos.set(op.id, posValue(next.position));
        }
        baseline?.data.set(op.id, dataValue(next));
        break;
      }
      case "node.pos": {
        const index = nodes.findIndex((item) => item.id === op.id);
        if (index < 0) break;
        nodes[index] = { ...nodes[index], position: { x: op.x, y: op.y } };
        baseline?.pos.set(op.id, posValue(nodes[index].position));
        break;
      }
      case "node.del": {
        if (!nodes.some((item) => item.id === op.id)) break;
        nodes = nodes.filter((item) => item.id !== op.id);
        baseline?.data.delete(op.id);
        baseline?.pos.delete(op.id);
        for (const edge of edges) {
          if (edge.source === op.id || edge.target === op.id) baseline?.edges.delete(edge.id);
        }
        edges = edges.filter((edge) => edge.source !== op.id && edge.target !== op.id);
        break;
      }
      case "edge.put": {
        const ids = new Set(nodes.map((item) => item.id));
        if (!ids.has(op.edge.source) || !ids.has(op.edge.target)) break;
        const edge = plainEdge(op.edge);
        const index = edges.findIndex((item) => item.id === op.id);
        if (index >= 0) edges[index] = edge;
        else edges.push(edge);
        baseline?.edges.set(op.id, edgeValue(edge));
        break;
      }
      case "edge.del": {
        if (!edges.some((item) => item.id === op.id)) break;
        edges = edges.filter((item) => item.id !== op.id);
        baseline?.edges.delete(op.id);
        break;
      }
    }
  }
  return { nodes, edges };
}

/**
 * The graph as the baseline last knew it, or null when nothing differs. A following tab uses it
 * to undo what a replayed click changed locally: the leader's own change arrives as ops.
 */
export function revertToBaseline(baseline: SyncBaseline, graph: SyncGraph): SyncGraph | null {
  const current = new Map(graph.nodes.map((node) => [node.id, node]));
  let changed = graph.nodes.length !== baseline.data.size || graph.edges.length !== baseline.edges.size;
  const nodes: WorkflowNode[] = [];
  for (const [id, data] of baseline.data) {
    const mine = current.get(id);
    const pos = baseline.pos.get(id) ?? "0,0";
    if (!mine || dataValue(mine) !== data || posValue(mine.position) !== pos) changed = true;
    const parsed = JSON.parse(data) as { type: WorkflowNode["type"]; data: NodeData };
    const [x, y] = pos.split(",").map(Number);
    nodes.push({
      id,
      type: parsed.type,
      position: { x, y },
      data: { ...parsed.data, ...runtimeData(mine?.data) },
    });
  }
  const currentEdges = new Map(graph.edges.map((edge) => [edge.id, edgeValue(edge)]));
  const edges: WorkflowEdge[] = [];
  for (const [id, value] of baseline.edges) {
    if (currentEdges.get(id) !== value) changed = true;
    edges.push(JSON.parse(value) as WorkflowEdge);
  }
  return changed ? { nodes, edges } : null;
}

/** Applies remote ops to every undo snapshot, so undo reverts only this canvas's own edits. */
export function rebaseHistory(
  states: SyncGraph[],
  ops: SyncOp[],
  isPending: PendingCheck,
): SyncGraph[] {
  return states.map((state) => applyOps(state, ops, isPending));
}

/** A peer's snapshot, except keys this canvas has unacknowledged edits for: those stay local. */
export function mergeSnapshot(
  local: SyncGraph,
  snapshot: SyncGraph,
  isPending: PendingCheck,
): SyncGraph {
  const localNodes = new Map(local.nodes.map((item) => [item.id, item]));
  const localEdges = new Map(local.edges.map((item) => [item.id, item]));
  const nodes: WorkflowNode[] = [];
  const seenNodes = new Set<string>();
  for (const remote of snapshot.nodes) {
    seenNodes.add(remote.id);
    const mine = localNodes.get(remote.id);
    const dataPending = isPending(nodeDataKey(remote.id));
    if (dataPending && !mine) continue;
    const base: WorkflowNode =
      dataPending && mine
        ? mine
        : { ...remote, data: { ...remote.data, ...runtimeData(mine?.data) } };
    const position = isPending(nodePosKey(remote.id)) && mine ? mine.position : remote.position;
    nodes.push({ ...base, position: { ...position } });
  }
  for (const mine of local.nodes) {
    if (!seenNodes.has(mine.id) && isPending(nodeDataKey(mine.id))) nodes.push(mine);
  }
  const nodeIds = new Set(nodes.map((item) => item.id));
  const edges: WorkflowEdge[] = [];
  const seenEdges = new Set<string>();
  for (const remote of snapshot.edges) {
    seenEdges.add(remote.id);
    const pending = isPending(edgeKey(remote.id));
    const mine = localEdges.get(remote.id);
    if (pending && !mine) continue;
    edges.push(plainEdge(pending && mine ? mine : remote));
  }
  for (const mine of local.edges) {
    if (!seenEdges.has(mine.id) && isPending(edgeKey(mine.id))) edges.push(plainEdge(mine));
  }
  return {
    nodes,
    edges: edges.filter((edge) => nodeIds.has(edge.source) && nodeIds.has(edge.target)),
  };
}

function compareIds(a: { id: string }, b: { id: string }): number {
  if (a.id < b.id) return -1;
  if (a.id > b.id) return 1;
  return 0;
}

function cyrb53(value: string): string {
  let h1 = 0xdeadbeef;
  let h2 = 0x41c6ce57;
  for (let index = 0; index < value.length; index += 1) {
    const code = value.charCodeAt(index);
    h1 = Math.imul(h1 ^ code, 2654435761);
    h2 = Math.imul(h2 ^ code, 1597334677);
  }
  h1 = Math.imul(h1 ^ (h1 >>> 16), 2246822507);
  h1 ^= Math.imul(h2 ^ (h2 >>> 13), 3266489909);
  h2 = Math.imul(h2 ^ (h2 >>> 16), 2246822507);
  h2 ^= Math.imul(h1 ^ (h1 >>> 13), 3266489909);
  return (4294967296 * (2097151 & h2) + (h1 >>> 0)).toString(36);
}

/** Order-independent hash of what a save stores. Equal hashes mean the same saved graph. */
export function stateHash(graph: SyncGraph): string {
  const nodes = [...graph.nodes].sort(compareIds).map((item) =>
    stableStringify({
      id: item.id,
      type: item.type,
      position: item.position,
      data: stripRuntimeData(item.data),
    }),
  );
  const edges = [...graph.edges].sort(compareIds).map(edgeValue);
  return cyrb53(`${nodes.join("\n")}|${edges.join("\n")}`);
}
