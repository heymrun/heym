import { describe, expect, it } from "vitest";

import { splitDriveAttachment } from "./chatAttachment";

describe("splitDriveAttachment", () => {
  it("hides the server's attachment block and keeps the file name", () => {
    const content =
      "Sum the Amount column\n\n[ATTACHED DRIVE FILE: q3.xlsx · id 1 · 10 bytes]\nThe file is in Heym Drive.";
    expect(splitDriveAttachment(content)).toEqual({ text: "Sum the Amount column", name: "q3.xlsx" });
  });

  it("leaves messages without an attachment alone", () => {
    expect(splitDriveAttachment("hello")).toEqual({ text: "hello", name: null });
  });
});
