import { describe, expect, it } from "vitest";

import { attachmentNames, splitAttachmentBlocks } from "./chatAttachment";

describe("splitAttachmentBlocks", () => {
  it("hides the server's attachment block and keeps the file name", () => {
    const content =
      "Sum the Amount column\n\n[ATTACHED DRIVE FILE: q3.xlsx · id 1 · 10 bytes]\nThe file is in Heym Drive.";
    expect(splitAttachmentBlocks(content)).toEqual({
      text: "Sum the Amount column",
      blocks: [{ kind: "drive", name: "q3.xlsx", body: "The file is in Heym Drive." }],
    });
  });

  it("splits several files of different kinds in order", () => {
    const content =
      "Compare these" +
      "\n\n[ATTACHED DRIVE FILE: report.pdf · id 1 · 10 bytes · application/pdf]\nIn Drive." +
      "\n\n[ATTACHED FILE: notes.py]\nprint('hi')\nprint('bye')" +
      "\n\n[ATTACHED DRIVE FILE: burak.akgun · id 2 · 65 bytes]\nIn Drive.";
    const split = splitAttachmentBlocks(content);
    expect(split.text).toBe("Compare these");
    expect(split.blocks.map((block) => [block.kind, block.name])).toEqual([
      ["drive", "report.pdf"],
      ["file", "notes.py"],
      ["drive", "burak.akgun"],
    ]);
    expect(split.blocks[1].body).toBe("print('hi')\nprint('bye')");
    expect(attachmentNames(content)).toEqual(["report.pdf", "notes.py", "burak.akgun"]);
  });

  it("leaves messages without an attachment alone", () => {
    expect(splitAttachmentBlocks("hello")).toEqual({ text: "hello", blocks: [] });
    expect(attachmentNames("hello")).toEqual([]);
  });
});
