import { createSSRApp, h, type Component } from "vue";
import { describe, expect, it } from "vitest";
import { renderToString } from "vue/server-renderer";

import SettingsTabNav from "@/components/Layout/settings/SettingsTabNav.vue";

const TABS = [
  { id: "profile", label: "Profile" },
  { id: "security", label: "Security" },
  { id: "encryption", label: "Encryption", testId: "settings-tab-encryption" },
];

async function renderNav(modelValue: string): Promise<string> {
  const app = createSSRApp({
    render: () => h(SettingsTabNav as Component, { tabs: TABS, modelValue }),
  });
  return renderToString(app);
}

function getButtons(html: string): string[] {
  return html.match(/<button[^>]*>[\s\S]*?<\/button>/g) ?? [];
}

describe("SettingsTabNav", () => {
  it("renders one button per tab in order", async () => {
    const buttons = getButtons(await renderNav("profile"));
    expect(buttons).toHaveLength(3);
    expect(buttons[0]).toContain("Profile");
    expect(buttons[1]).toContain("Security");
    expect(buttons[2]).toContain("Encryption");
  });

  it("marks only the selected tab with the underline and aria-current", async () => {
    const buttons = getButtons(await renderNav("security"));
    const [profile, security] = buttons;
    expect(security).toContain('aria-current="true"');
    expect(security).toContain("border-primary");
    expect(profile).not.toContain("aria-current");
    expect(profile).toContain("border-transparent");
  });

  it("stacks the tabs vertically from the sm breakpoint up", async () => {
    const html = await renderNav("profile");
    expect(html).toContain("sm:flex-col");
    expect(html).toContain("sm:w-40");
  });

  it("passes through a tab's test id", async () => {
    const buttons = getButtons(await renderNav("profile"));
    expect(buttons[2]).toContain('data-testid="settings-tab-encryption"');
    expect(buttons[0]).not.toContain("data-testid");
  });
});
