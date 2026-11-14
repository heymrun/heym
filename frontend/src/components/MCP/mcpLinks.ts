import type { MCPServerItem } from "@/services/api";
import { joinOriginAndPath } from "@/lib/appUrl";

/** Default MCP endpoint URL (Streamable HTTP at `/api/mcp`). */
export function defaultMcpEndpointUrl(origin: string): string {
  return joinOriginAndPath(origin, "/api/mcp");
}

/**
 * Named MCP server endpoint URL.
 * Newly created servers use `/mcp`; legacy servers continue using their persisted `endpoint_path` (e.g. `sse`).
 */
export function namedServerMcpEndpointUrl(
  origin: string,
  server: Pick<MCPServerItem, "id"> & { endpoint_path?: string | null },
): string {
  const path = server.endpoint_path === "sse" ? "sse" : "mcp";
  return joinOriginAndPath(origin, `/api/mcp/servers/${server.id}/${path}`);
}

export interface ClientMcpConfigItem {
  url: string;
  headers: Record<string, string>;
}

export interface ClientMcpConfig {
  mcpServers: Record<string, ClientMcpConfigItem>;
}

/** Build MCP client JSON configuration for the default server. */
export function buildDefaultMcpConfig(
  origin: string,
  apiKey: string = "YOUR_API_KEY",
): ClientMcpConfig {
  return {
    mcpServers: {
      heym: {
        url: defaultMcpEndpointUrl(origin),
        headers: {
          "X-MCP-Key": apiKey,
        },
      },
    },
  };
}

/** Build Cursor install deep link for the default server. */
export function buildDefaultCursorDeepLink(
  origin: string,
  apiKey: string = "YOUR_API_KEY",
): string {
  const config = {
    url: defaultMcpEndpointUrl(origin),
    headers: {
      "X-MCP-Key": apiKey,
    },
  };
  const configBase64 = btoa(JSON.stringify(config));
  return `cursor://anysphere.cursor-deeplink/mcp/install?name=${encodeURIComponent("heym")}&config=${configBase64}`;
}

/** Build MCP client JSON configuration for a named server. */
export function buildNamedServerMcpConfig(
  origin: string,
  server: Pick<MCPServerItem, "id" | "name"> & { endpoint_path?: string | null },
  apiKey: string = "YOUR_API_KEY",
): ClientMcpConfig {
  const key = server.name.toLowerCase().replace(/\s+/g, "_");
  return {
    mcpServers: {
      [key]: {
        url: namedServerMcpEndpointUrl(origin, server),
        headers: {
          "X-MCP-Key": apiKey,
        },
      },
    },
  };
}

/** Build Cursor install deep link for a named server. */
export function buildNamedServerCursorDeepLink(
  origin: string,
  server: Pick<MCPServerItem, "id" | "name"> & { endpoint_path?: string | null },
  apiKey: string = "YOUR_API_KEY",
): string {
  const config = {
    url: namedServerMcpEndpointUrl(origin, server),
    headers: {
      "X-MCP-Key": apiKey,
    },
  };
  const configBase64 = btoa(JSON.stringify(config));
  return `cursor://anysphere.cursor-deeplink/mcp/install?name=${encodeURIComponent(server.name)}&config=${configBase64}`;
}
