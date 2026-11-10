import { readFileSync } from "node:fs";

import { describe, expect, it } from "vitest";

import { renderDocMarkdown, resolveDocLink } from "@/docs/renderMarkdown";

describe("documentation navigation", () => {
  it("resolves sibling and parent article links with their section anchors", () => {
    expect(resolveDocLink("./operations-runbook.md#cluster-mode-checks", "reference/incident-playbook"))
      .toBe("/docs/reference/operations-runbook#cluster-mode-checks");
    expect(resolveDocLink("../reference/incident-playbook.md", "tabs/logs-tab"))
      .toBe("/docs/reference/incident-playbook");
    expect(resolveDocLink("#command-setup", "reference/operations-runbook"))
      .toBe("#command-setup");
    expect(resolveDocLink("https://example.com/guide.md", "reference/operations-runbook"))
      .toBe("https://example.com/guide.md");
  });

  it("gives formatted headings GitHub IDs and disambiguates repeated headings per article", () => {
    const source = "## [Database](./operations-runbook.md) checks\n\n## Database checks";
    const html = renderDocMarkdown(source, "reference/incident-playbook");
    expect(html).toContain('id="database-checks"');
    expect(html).toContain('id="database-checks-1"');
    expect(renderDocMarkdown("## Database checks", "reference/another"))
      .toContain('id="database-checks"');
  });

  it("keeps local anchors in the same tab and escapes code examples", () => {
    const html = renderDocMarkdown('[Setup](#command-setup)\n\n```bash\necho "<input>"\n```', "reference/operations-runbook");
    expect(html).toContain('<a href="#command-setup">Setup</a>');
    expect(html).toContain('echo &quot;&lt;input&gt;&quot;');
  });

  it("renders an existing heading target for every incident routing and procedure link", () => {
    const articles = Object.fromEntries(["incident-playbook", "operations-runbook"].map((slug) => [
      slug, readFileSync(new URL(`./content/reference/${slug}.md`, import.meta.url), "utf8"),
    ]));
    const rendered = Object.fromEntries(Object.entries(articles).map(([slug, source]) => [
      slug, renderDocMarkdown(source, `reference/${slug}`),
    ]));

    for (const [slug, html] of Object.entries(rendered)) {
      for (const match of html.matchAll(/href="(?:\/docs\/reference\/([^"#]+))?#([^"#]+)"/g)) {
        const target = rendered[match[1] ?? slug];
        if (target) expect(target, `${slug}: ${match[0]}`).toContain(`id="${match[2]}"`);
      }
    }
  });
});
