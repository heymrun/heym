import { describe, expect, it } from "vitest";

import type { AgentSkillFile } from "@/types/workflow";
import {
  getSkillFilesSortedForDisplay,
  isEditableSkillFile,
  sortSkillFiles,
} from "@/lib/skillFilePreview";

function makeFile(
  path: string,
  encoding: AgentSkillFile["encoding"] = "text",
): AgentSkillFile {
  return {
    path,
    content: encoding === "base64" ? "YWJj" : `# ${path}`,
    encoding,
    mimeType: encoding === "base64" ? "application/pdf" : "text/plain",
  };
}

describe("skillFilePreview", () => {
  it("treats text and svg files as editable", () => {
    expect(isEditableSkillFile(makeFile("main.py"))).toBe(true);
    expect(isEditableSkillFile(makeFile("icon.svg"))).toBe(true);
    expect(isEditableSkillFile(makeFile("doc.pdf", "base64"))).toBe(false);
  });

  it("sorts editable files before binary attachments", () => {
    const files = [
      makeFile("assets/report.pdf", "base64"),
      makeFile("tools/run.py"),
      makeFile("README.md"),
    ];

    expect(sortSkillFiles(files).map((file) => file.path)).toEqual([
      "README.md",
      "tools/run.py",
      "assets/report.pdf",
    ]);
  });

  it("preserves original indices for sorted display entries", () => {
    const files = [
      makeFile("assets/report.pdf", "base64"),
      makeFile("tools/run.py"),
      makeFile("README.md"),
    ];

    expect(getSkillFilesSortedForDisplay(files)).toEqual([
      { file: files[2], originalIndex: 2 },
      { file: files[1], originalIndex: 1 },
      { file: files[0], originalIndex: 0 },
    ]);
  });
});
