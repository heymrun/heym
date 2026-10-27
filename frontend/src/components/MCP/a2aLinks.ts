import type { MCPChatToolConfig } from "@/services/api";
import { joinOriginAndPath } from "@/lib/appUrl";

/** The JSON-RPC endpoint of the global agent (`serverId` null) or a named server's agent. */
export function a2aEndpointUrl(origin: string, serverId: string | null): string {
  const path = serverId ? `/api/a2a/servers/${serverId}` : "/api/a2a";
  return joinOriginAndPath(origin, path);
}

/** Where an A2A client discovers the agent: the domain card, or the named server's card. */
export function a2aAgentCardUrl(origin: string, serverId: string | null): string {
  if (!serverId) return joinOriginAndPath(origin, "/.well-known/agent-card.json");
  return `${a2aEndpointUrl(origin, serverId)}/agent-card.json`;
}

/** A command that proves the card is live; the card itself needs no credentials. */
export function a2aCurlExample(cardUrl: string): string {
  return `curl ${cardUrl}`;
}

/** One line on where the Heym Agent answers right now. */
export function agentReachText(chatTool: MCPChatToolConfig, configured: boolean): string {
  if (!chatTool.enabled) return "Off: MCP and A2A clients cannot reach the Heym Agent";
  if (!configured) return "Pick a credential and a model so the Heym Agent can run";
  if (chatTool.a2a_enabled) return "Reachable over MCP and A2A";
  return "Reachable as heym_chat over MCP";
}
