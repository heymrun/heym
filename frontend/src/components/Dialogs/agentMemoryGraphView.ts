import type { AgentMemoryEdgeDTO, AgentMemoryNodeDTO } from "@/types/agentMemory";

export interface XYPosition {
  x: number;
  y: number;
}

/** Total in+out edge count per node id. */
export function computeDegrees(
  nodes: AgentMemoryNodeDTO[],
  edges: AgentMemoryEdgeDTO[],
): Map<string, number> {
  const degree = new Map<string, number>();
  for (const n of nodes) {
    degree.set(n.id, 0);
  }
  for (const e of edges) {
    if (degree.has(e.source_node_id)) {
      degree.set(e.source_node_id, (degree.get(e.source_node_id) ?? 0) + 1);
    }
    if (degree.has(e.target_node_id)) {
      degree.set(e.target_node_id, (degree.get(e.target_node_id) ?? 0) + 1);
    }
  }
  return degree;
}

const MIN_RADIUS = 11;
const MAX_RADIUS = 22;
const MAX_DEGREE_FOR_SCALE = 8;

/** Circle radius in px, scaled by connection count (capped so hub nodes don't dominate). */
export function nodeRadius(degree: number): number {
  const clamped = Math.max(0, Math.min(degree, MAX_DEGREE_FOR_SCALE));
  const t = clamped / MAX_DEGREE_FOR_SCALE;
  return Math.round(MIN_RADIUS + t * (MAX_RADIUS - MIN_RADIUS));
}

/** Subtle blue-family palette; stable per entity type via hashing (no external deps). */
const CLUSTER_PALETTE = [
  "#60a5fa",
  "#38bdf8",
  "#818cf8",
  "#22d3ee",
  "#a5b4fc",
  "#7dd3fc",
  "#93c5fd",
  "#5eead4",
];

function hashString(value: string): number {
  let hash = 0;
  for (let i = 0; i < value.length; i++) {
    hash = (hash * 31 + value.charCodeAt(i)) | 0;
  }
  return Math.abs(hash);
}

function normalizedType(entityType: string): string {
  return entityType.trim().toLowerCase() || "unknown";
}

export function clusterColorForType(entityType: string): string {
  const key = normalizedType(entityType);
  return CLUSTER_PALETTE[hashString(key) % CLUSTER_PALETTE.length]!;
}

/** Stable, sorted list of distinct entity types (for cluster anchoring and the legend). */
export function distinctEntityTypes(nodes: AgentMemoryNodeDTO[]): string[] {
  const seen = new Set<string>();
  for (const n of nodes) {
    seen.add(normalizedType(n.entity_type));
  }
  return [...seen].sort((a, b) => a.localeCompare(b));
}

export interface SeedPositionOptions {
  centerX?: number;
  centerY?: number;
  clusterRadius?: number;
}

/**
 * Deterministic cluster-anchored seed layout: each entity type gets a ring anchor around the
 * canvas center, and nodes jitter around their type's anchor by a stable per-id hash. Used only
 * to place brand-new nodes; existing nodes keep their live (dragged/simulated) position — see
 * AgentMemoryGraphDialog.vue's `knownPositions`.
 */
export function seedPositions(
  nodes: AgentMemoryNodeDTO[],
  opts?: SeedPositionOptions,
): Map<string, XYPosition> {
  const centerX = opts?.centerX ?? 480;
  const centerY = opts?.centerY ?? 320;
  const clusterRadius = opts?.clusterRadius ?? 260;

  const types = distinctEntityTypes(nodes);
  const anchors = new Map<string, XYPosition>();
  if (types.length <= 1) {
    anchors.set(types[0] ?? "unknown", { x: centerX, y: centerY });
  } else {
    types.forEach((type, i) => {
      const angle = (2 * Math.PI * i) / types.length;
      anchors.set(type, {
        x: centerX + clusterRadius * Math.cos(angle),
        y: centerY + clusterRadius * Math.sin(angle),
      });
    });
  }

  const pos = new Map<string, XYPosition>();
  for (const n of nodes) {
    const anchor = anchors.get(normalizedType(n.entity_type)) ?? { x: centerX, y: centerY };
    const h = hashString(n.id);
    const jitterAngle = (h % 360) * (Math.PI / 180);
    const jitterRadius = 30 + (h % 70);
    pos.set(n.id, {
      x: anchor.x + jitterRadius * Math.cos(jitterAngle),
      y: anchor.y + jitterRadius * Math.sin(jitterAngle),
    });
  }
  return pos;
}
