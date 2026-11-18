/** Matches the backend's MemoryAiInsertRequest.text cap. */
export const AI_INSERT_MAX_CHARS = 24000;

export interface AgentMemoryModelChoice {
  credentialId: string;
  model: string;
}

/**
 * The credential and model the agent node itself is set to, or null when either is missing.
 * AI insert runs on exactly what the agent uses, so an agent without a model has no AI insert.
 */
export function agentModelChoice(
  data: Record<string, unknown> | undefined | null,
): AgentMemoryModelChoice | null {
  const credentialId = typeof data?.credentialId === "string" ? data.credentialId.trim() : "";
  const model = typeof data?.model === "string" ? data.model.trim() : "";
  if (!credentialId || !model) {
    return null;
  }
  return { credentialId, model };
}

export function aiInsertTooltip(model: string | null): string {
  if (!model) {
    return "Select a credential and model on this agent to use AI insert";
  }
  return `AI insert: extract entities and relationships from text with ${model}`;
}

export function clearAllTooltip(entityCount: number): string {
  if (entityCount === 0) {
    return "Memory is already empty";
  }
  return "Clear all: delete every entity and relationship in this memory";
}

function plural(count: number, one: string, many: string): string {
  return `${String(count)} ${count === 1 ? one : many}`;
}

export function clearAllConfirmText(entityCount: number, relationshipCount: number): string {
  return (
    `Delete ${plural(entityCount, "entity", "entities")} and ` +
    `${plural(relationshipCount, "relationship", "relationships")} from this agent's memory? ` +
    "This cannot be undone."
  );
}

function nearestScrollParent(el: HTMLElement): HTMLElement | null {
  for (let parent = el.parentElement; parent; parent = parent.parentElement) {
    const overflowY = getComputedStyle(parent).overflowY;
    if ((overflowY === "auto" || overflowY === "scroll") && parent.scrollHeight > parent.clientHeight) {
      return parent;
    }
  }
  return null;
}

/**
 * Scrolls the nearest scrollable ancestor down until `el`'s bottom edge is in view, without
 * pushing its top edge out of view. Overflow-hidden ancestors are skipped on purpose:
 * `scrollIntoView` would scroll them too, and the user has no way to scroll them back.
 */
export function revealBelow(el: HTMLElement): void {
  const scroller = nearestScrollParent(el);
  if (!scroller) {
    return;
  }
  const box = el.getBoundingClientRect();
  const view = scroller.getBoundingClientRect();
  const delta = Math.min(box.bottom - view.bottom, box.top - view.top);
  if (delta <= 0) {
    return;
  }
  const reduceMotion = window.matchMedia?.("(prefers-reduced-motion: reduce)").matches ?? false;
  scroller.scrollBy({ top: delta, behavior: reduceMotion ? "auto" : "smooth" });
}

/** Toast text after an insert, or null when the model found nothing to add. */
export function aiInsertSummary(entities: number, relationships: number): string | null {
  if (entities === 0 && relationships === 0) {
    return null;
  }
  return (
    `Inserted ${plural(entities, "entity", "entities")} and ` +
    `${plural(relationships, "relationship", "relationships")}`
  );
}
