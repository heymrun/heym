import { existsSync, readFileSync, statSync } from "node:fs";
import { dirname, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { describe, expect, it } from "vitest";

const SRC = resolve(dirname(fileURLToPath(import.meta.url)), "..");

/**
 * The components and modules Heym Work imports from Heym, and everything they import in turn.
 * Add a file here when Work starts using it.
 */
const PRESENTATIONAL = [
  "components/Chat/ChatToolCall.vue",
  "components/Chat/InteractiveVoiceMode.vue",
  "components/Dashboards/ChartView.vue",
  "components/Dashboards/HitlCarousel.vue",
  "components/Dashboards/HitlReviewActions.vue",
  "composables/clarifyDataTables.ts",
  "composables/interactiveVoice.ts",
  "composables/textToSpeechPlayer.ts",
  "composables/useFileAttachment.ts",
  "features/assistant-yolo/components/YoloStepList.vue",
  "ports/index.ts",
];

/** In Work these resolve to Work's API client, stores and router, or to nothing at all. */
const FORBIDDEN = [/^@\/services\//, /^@\/stores\//, /^axios$/, /^pinia$/, /^vue-router$/];

// Static imports and re-exports (type-only ones too), dynamic imports, side-effect imports.
const SPECIFIER = /\bfrom\s*["']([^"']+)["']|\bimport\s*\(\s*["']([^"']+)["']\s*\)|\bimport\s+["']([^"']+)["']/g;

function resolveImport(specifier: string, importer: string): string | null {
  let base: string;
  if (specifier.startsWith("@/")) base = resolve(SRC, specifier.slice(2));
  else if (specifier.startsWith(".")) base = resolve(dirname(importer), specifier);
  else return null;
  for (const candidate of [base, `${base}.ts`, resolve(base, "index.ts")]) {
    if (existsSync(candidate) && statSync(candidate).isFile()) return candidate;
  }
  return null;
}

/** Every forbidden import reachable from `entries`, with the path that reaches it. */
function forbiddenImports(entries: string[]): string[] {
  const importedBy = new Map<string, string | null>();
  // Entries that do not exist yet are reported by "lists files that exist".
  const queue: Array<{ file: string; importer: string | null }> = entries
    .map((entry) => resolve(SRC, entry))
    .filter((file) => existsSync(file))
    .map((file) => ({ file, importer: null }));
  const found: string[] = [];
  while (queue.length > 0) {
    const { file, importer } = queue.shift()!;
    if (importedBy.has(file)) continue;
    importedBy.set(file, importer);
    for (const match of readFileSync(file, "utf8").matchAll(SPECIFIER)) {
      const specifier = match[1] ?? match[2] ?? match[3];
      if (FORBIDDEN.some((pattern) => pattern.test(specifier))) {
        const path: string[] = [];
        for (let at: string | null = file; at; at = importedBy.get(at) ?? null) {
          path.unshift(relative(SRC, at));
        }
        found.push(`${path.join(" -> ")} imports ${specifier}`);
        continue;
      }
      const target = resolveImport(specifier, file);
      if (target && /\.(ts|vue)$/.test(target)) queue.push({ file: target, importer: file });
    }
  }
  return found;
}

describe("presentational components", () => {
  it("lists files that exist", () => {
    expect(PRESENTATIONAL.filter((entry) => !existsSync(resolve(SRC, entry)))).toEqual([]);
  });

  it("never import Heym's API client, stores or router", () => {
    expect(forbiddenImports(PRESENTATIONAL)).toEqual([]);
  });

  it("are checked by a scan that finds those imports", () => {
    expect(forbiddenImports(["stores/auth.ts"])).toContain("stores/auth.ts imports pinia");
  });
});
