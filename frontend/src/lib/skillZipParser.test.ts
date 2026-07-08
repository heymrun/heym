import JSZip from "jszip";
import { describe, expect, it } from "vitest";

import {
  parseSkillAssetFile,
  parseSkillZip,
  shouldIgnoreSkillArchivePath,
} from "@/lib/skillZipParser";

async function makeZipFile(entries: Record<string, string | Uint8Array>): Promise<File> {
  const zip = new JSZip();
  Object.entries(entries).forEach(([path, content]) => {
    zip.file(path, content);
  });
  const blob = await zip.generateAsync({ type: "blob" });
  return new File([blob], "skill.zip", { type: "application/zip" });
}

describe("skillZipParser", () => {
  it("skips macOS metadata files when importing a skill zip", async () => {
    const file = await makeZipFile({
      "SKILL.md": "---\nname: useful-skill\n---",
      "main.py": "def execute(params, files):\n    return {}\n",
      ".DS_Store": "metadata",
      "__MACOSX/SKILL.md": "---\nname: ignored\n---",
      "__MACOSX/._main.py": "metadata",
      "assets/._hello.pdf": "metadata",
    });

    const skills = await parseSkillZip(file);

    expect(skills).toHaveLength(1);
    expect(skills[0]?.name).toBe("useful-skill");
    expect(skills[0]?.files?.map((skillFile) => skillFile.path)).toEqual(["main.py"]);
  });

  it("parses a dropped binary file as a base64 skill attachment", async () => {
    const file = new File([new Uint8Array([0, 1, 2, 3])], "hello.pdf", {
      type: "application/pdf",
    });

    const parsed = await parseSkillAssetFile(file);

    expect(parsed).toEqual({
      path: "hello.pdf",
      content: "AAECAw==",
      encoding: "base64",
      mimeType: "application/pdf",
    });
  });

  it("marks macOS archive metadata paths as ignored", () => {
    expect(shouldIgnoreSkillArchivePath("__MACOSX/._main.py")).toBe(true);
    expect(shouldIgnoreSkillArchivePath("assets/.DS_Store")).toBe(true);
    expect(shouldIgnoreSkillArchivePath("assets/main.py")).toBe(false);
  });
});
