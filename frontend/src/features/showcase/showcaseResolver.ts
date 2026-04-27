import { getAllDocItems } from "@/docs/manifest";
import { SHOWCASE_DEFINITIONS } from "@/features/showcase/showcaseRegistry";
import type {
  ResolveShowcaseContextOptions,
  ResolveShowcaseDefinitionOptions,
  ShowcaseContext,
  ShowcaseDefinition,
  ShowcaseDocTarget,
} from "@/features/showcase/showcase.types";

function parseDocPath(currentDocPath: string | null | undefined): ShowcaseDocTarget | null {
  if (!currentDocPath) return null;

  const normalized = currentDocPath.replace(/^\//, "").replace(/\/$/, "");
  const segments = normalized.split("/");
  if (segments.length !== 2) return null;

  const [categoryId, slug] = segments;
  const match = getAllDocItems().find((item) => item.categoryId === categoryId && item.slug === slug);
  if (!match) return null;

  return {
    categoryId,
    slug,
    title: match.title,
  };
}

export function resolveShowcaseContext(
  options: ResolveShowcaseContextOptions,
): ShowcaseContext | null {
  if (options.routePath.startsWith("/workflows/")) {
    return "editor";
  }
  if (options.routePath.startsWith("/evals")) {
    return "evals";
  }
  if (options.routePath.startsWith("/docs")) {
    return "docs";
  }
  if (options.routePath === "/") {
    return `dashboard:${options.dashboardTab ?? "workflows"}`;
  }
  return null;
}

export function resolveShowcaseDefinition(
  options: ResolveShowcaseDefinitionOptions,
): ShowcaseDefinition | null {
  if (!options.context) return null;

  const definition = SHOWCASE_DEFINITIONS[options.context];
  if (!definition) return null;

  if (options.context !== "docs") {
    return definition;
  }

  const currentDocTarget = parseDocPath(options.currentDocPath);
  if (!currentDocTarget) {
    return definition;
  }

  const docsAction = definition.actions[0];
  return {
    ...definition,
    actions: docsAction
      ? [
          {
            ...docsAction,
            label: currentDocTarget.title ? `Read ${currentDocTarget.title}` : "Read this article",
            description: "Open the article you are currently browsing.",
            docTarget: currentDocTarget,
          },
        ]
      : definition.actions,
    docsTarget: currentDocTarget,
  };
}
