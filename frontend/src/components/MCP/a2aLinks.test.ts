import { describe, expect, it } from "vitest";

import type { MCPChatToolConfig } from "@/services/api";
import {
  a2aAgentCardUrl,
  a2aCurlExample,
  a2aEndpointUrl,
  agentReachText,
} from "@/components/MCP/a2aLinks";

const ORIGIN = "https://heym.example.com";
const SERVER = "6f2d8e0a-1b2c-4d3e-8f90-123456789abc";

function tool(overrides: Partial<MCPChatToolConfig>): MCPChatToolConfig {
  return { enabled: true, credential_id: "c", model: "m", a2a_enabled: false, ...overrides };
}

describe("A2A addresses", () => {
  it("serves the global agent at the domain card and /api/a2a", () => {
    expect(a2aAgentCardUrl(ORIGIN, null)).toBe(`${ORIGIN}/.well-known/agent-card.json`);
    expect(a2aEndpointUrl(ORIGIN, null)).toBe(`${ORIGIN}/api/a2a`);
  });

  it("serves a named server under its own path", () => {
    expect(a2aEndpointUrl(`${ORIGIN}/`, SERVER)).toBe(`${ORIGIN}/api/a2a/servers/${SERVER}`);
    expect(a2aAgentCardUrl(ORIGIN, SERVER)).toBe(
      `${ORIGIN}/api/a2a/servers/${SERVER}/agent-card.json`,
    );
  });

  it("shows how to fetch the card", () => {
    expect(a2aCurlExample(`${ORIGIN}/api/a2a`)).toBe(`curl ${ORIGIN}/api/a2a`);
  });
});

describe("agentReachText", () => {
  it("says where the agent answers", () => {
    expect(agentReachText(tool({ enabled: false }), true)).toBe(
      "Off: MCP and A2A clients cannot reach the Heym Agent",
    );
    expect(agentReachText(tool({}), true)).toBe("Reachable as heym_chat over MCP");
    expect(agentReachText(tool({ a2a_enabled: true }), true)).toBe("Reachable over MCP and A2A");
    expect(agentReachText(tool({ a2a_enabled: true }), false)).toBe(
      "Pick a credential and a model so the Heym Agent can run",
    );
  });
});
