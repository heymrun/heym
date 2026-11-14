import { describe, expect, it } from "vitest";

import {
  buildDefaultCursorDeepLink,
  buildDefaultMcpConfig,
  buildNamedServerCursorDeepLink,
  buildNamedServerMcpConfig,
  defaultMcpEndpointUrl,
  namedServerMcpEndpointUrl,
} from "@/components/MCP/mcpLinks";

const ORIGIN = "https://heym.example.com";
const SERVER_ID = "6f2d8e0a-1b2c-4d3e-8f90-123456789abc";

function decodeCursorConfig(deepLink: string): { url: string; headers: Record<string, string> } {
  const url = new URL(deepLink);
  const configBase64 = url.searchParams.get("config") || "";
  const jsonStr = atob(configBase64);
  return JSON.parse(jsonStr);
}

describe("defaultMcpEndpointUrl", () => {
  it("uses the modern /api/mcp endpoint", () => {
    expect(defaultMcpEndpointUrl(ORIGIN)).toBe(`${ORIGIN}/api/mcp`);
  });

  it("handles origins with trailing slash cleanly", () => {
    expect(defaultMcpEndpointUrl(`${ORIGIN}/`)).toBe(`${ORIGIN}/api/mcp`);
  });
});

describe("namedServerMcpEndpointUrl", () => {
  it("constructs /mcp URL for newly created servers (default or endpoint_path='mcp')", () => {
    expect(namedServerMcpEndpointUrl(ORIGIN, { id: SERVER_ID, endpoint_path: "mcp" })).toBe(
      `${ORIGIN}/api/mcp/servers/${SERVER_ID}/mcp`,
    );
    expect(namedServerMcpEndpointUrl(ORIGIN, { id: SERVER_ID })).toBe(
      `${ORIGIN}/api/mcp/servers/${SERVER_ID}/mcp`,
    );
  });

  it("constructs /sse URL for legacy servers with endpoint_path='sse'", () => {
    expect(namedServerMcpEndpointUrl(ORIGIN, { id: SERVER_ID, endpoint_path: "sse" })).toBe(
      `${ORIGIN}/api/mcp/servers/${SERVER_ID}/sse`,
    );
  });
});

describe("buildDefaultMcpConfig", () => {
  it("generates client configuration pointing to /api/mcp", () => {
    const config = buildDefaultMcpConfig(ORIGIN, "test-secret-key");
    expect(config).toEqual({
      mcpServers: {
        heym: {
          url: `${ORIGIN}/api/mcp`,
          headers: {
            "X-MCP-Key": "test-secret-key",
          },
        },
      },
    });
  });
});

describe("buildDefaultCursorDeepLink", () => {
  it("generates Cursor install deep link encoding /api/mcp", () => {
    const link = buildDefaultCursorDeepLink(ORIGIN, "cursor-key");
    expect(link.startsWith("cursor://anysphere.cursor-deeplink/mcp/install?name=heym&config=")).toBe(true);
    const decoded = decodeCursorConfig(link);
    expect(decoded.url).toBe(`${ORIGIN}/api/mcp`);
    expect(decoded.headers["X-MCP-Key"]).toBe("cursor-key");
  });
});

describe("buildNamedServerMcpConfig", () => {
  it("generates config pointing to /api/mcp/servers/{id}/mcp for newly created servers", () => {
    const newServer = { id: SERVER_ID, name: "Analytics Server", endpoint_path: "mcp" };
    const config = buildNamedServerMcpConfig(ORIGIN, newServer, "named-key-1");
    expect(config).toEqual({
      mcpServers: {
        analytics_server: {
          url: `${ORIGIN}/api/mcp/servers/${SERVER_ID}/mcp`,
          headers: {
            "X-MCP-Key": "named-key-1",
          },
        },
      },
    });
  });

  it("generates config pointing to /api/mcp/servers/{id}/sse for legacy servers", () => {
    const legacyServer = { id: SERVER_ID, name: "Legacy Sync", endpoint_path: "sse" };
    const config = buildNamedServerMcpConfig(ORIGIN, legacyServer, "legacy-key-2");
    expect(config).toEqual({
      mcpServers: {
        legacy_sync: {
          url: `${ORIGIN}/api/mcp/servers/${SERVER_ID}/sse`,
          headers: {
            "X-MCP-Key": "legacy-key-2",
          },
        },
      },
    });
  });
});

describe("buildNamedServerCursorDeepLink", () => {
  it("generates Cursor deep link with /mcp endpoint for newly created servers", () => {
    const newServer = { id: SERVER_ID, name: "Production AI", endpoint_path: "mcp" };
    const link = buildNamedServerCursorDeepLink(ORIGIN, newServer, "prod-key");
    const decoded = decodeCursorConfig(link);
    expect(decoded.url).toBe(`${ORIGIN}/api/mcp/servers/${SERVER_ID}/mcp`);
    expect(decoded.headers["X-MCP-Key"]).toBe("prod-key");
  });

  it("generates Cursor deep link with /sse endpoint for legacy servers", () => {
    const legacyServer = { id: SERVER_ID, name: "Old Gateway", endpoint_path: "sse" };
    const link = buildNamedServerCursorDeepLink(ORIGIN, legacyServer, "old-key");
    const decoded = decodeCursorConfig(link);
    expect(decoded.url).toBe(`${ORIGIN}/api/mcp/servers/${SERVER_ID}/sse`);
    expect(decoded.headers["X-MCP-Key"]).toBe("old-key");
  });
});
