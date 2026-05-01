import type { WorkflowNode } from "@/types/workflow";

export interface MeasuredNodeLayout {
  id: string;
  dimensions?: {
    width: number;
    height: number;
  };
}

export interface NodeLayoutSize {
  width: number;
  height: number;
}

const DEFAULT_NODE_WIDTH = 200;
const DEFAULT_NODE_HEIGHT = 80;
const MIN_RENDERED_NODE_WIDTH = 190;

function estimatedTextWidth(text: string, maxWidth: number): number {
  return Math.min(text.length * 8, maxWidth);
}

function estimateNodeWidth(node: WorkflowNode, isSubAgent: boolean): number {
  if (node.type !== "agent") {
    return DEFAULT_NODE_WIDTH;
  }

  const labelWidth = estimatedTextWidth(String(node.data.label ?? "agent"), 140);
  const iconWidth = 36;
  const iconGap = 14;
  const horizontalPadding = 32;
  const retryBadgeWidth = node.data.retryEnabled ? 20 : 0;
  const subAgentBadgeWidth = isSubAgent ? 88 : 0;
  const hitlBadgeWidth = node.data.hitlEnabled ? 44 : 0;

  return Math.max(
    MIN_RENDERED_NODE_WIDTH,
    iconWidth + iconGap + labelWidth + retryBadgeWidth + subAgentBadgeWidth + hitlBadgeWidth + horizontalPadding,
  );
}

export function buildMeasuredNodeSizeMap(
  nodes: readonly MeasuredNodeLayout[],
): Map<string, NodeLayoutSize> {
  const sizes = new Map<string, NodeLayoutSize>();

  for (const node of nodes) {
    const width = node.dimensions?.width;
    const height = node.dimensions?.height;
    if (width === undefined || height === undefined || width <= 0 || height <= 0) {
      continue;
    }

    sizes.set(node.id, {
      width: Math.ceil(width),
      height: Math.ceil(height),
    });
  }

  return sizes;
}

export function getWorkflowNodeLayoutSize(
  node: WorkflowNode,
  measuredSizes: ReadonlyMap<string, NodeLayoutSize>,
  options: { isSubAgent?: boolean } = {},
): NodeLayoutSize {
  const measured = measuredSizes.get(node.id);
  const estimatedWidth = estimateNodeWidth(node, options.isSubAgent === true);
  return {
    width: Math.max(measured?.width ?? 0, estimatedWidth),
    height: measured?.height ?? DEFAULT_NODE_HEIGHT,
  };
}
