import vue from "@vitejs/plugin-vue";
import fs from "node:fs";
import type { ClientRequest, IncomingMessage, ServerResponse } from "node:http";
import path from "node:path";
import { fileURLToPath, URL } from "node:url";
import { defineConfig, type ProxyOptions } from "vite";

const apiTarget = process.env.VITE_API_TARGET || "http://localhost:10105";

const getVersion = (): string => {
  const versionCandidates = [
    path.resolve(process.cwd(), "VERSION"),
    path.resolve(process.cwd(), "../VERSION"),
    path.resolve(fileURLToPath(new URL(".", import.meta.url)), "../VERSION"),
  ];

  for (const versionPath of versionCandidates) {
    try {
      return fs.readFileSync(versionPath, "utf-8").trim();
    } catch {
      continue;
    }
  }

  return "0.1.0";
};

const APP_VERSION = process.env.APP_VERSION || getVersion();

const apiProxyOptions: ProxyOptions = {
  target: apiTarget,
  changeOrigin: true,
  ws: true,
  configure: (proxy) => {
    proxy.on("proxyReq", (proxyReq: ClientRequest, req: IncomingMessage) => {
      if (req.headers["cf-connecting-ip"]) {
        proxyReq.setHeader("CF-Connecting-IP", req.headers["cf-connecting-ip"]);
      }
      if (req.headers["x-forwarded-for"]) {
        proxyReq.setHeader("X-Forwarded-For", req.headers["x-forwarded-for"]);
      }
    });
    proxy.on("proxyRes", (proxyRes: IncomingMessage, _req: IncomingMessage, _res: ServerResponse) => {
      delete proxyRes.headers["transfer-encoding"];
    });
  },
};

const proxyConfig: Record<string, ProxyOptions> = {
  "/api": apiProxyOptions,
  "/.well-known/oauth-authorization-server": apiProxyOptions,
  "/authorize": apiProxyOptions,
  "/token": apiProxyOptions,
  "/register": apiProxyOptions,
};

const heymDevHeaders = {
  "X-Heym-Agent": "heym.run",
  Server: "heym.run",
};

export default defineConfig({
  plugins: [vue()],
  define: {
    "import.meta.env.VITE_APP_VERSION": JSON.stringify(APP_VERSION),
  },
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    port: 4017,
    host: "0.0.0.0",
    headers: heymDevHeaders,
    proxy: proxyConfig,
  },
  preview: {
    port: 4017,
    host: "0.0.0.0",
    allowedHosts: true,
    headers: heymDevHeaders,
    proxy: proxyConfig,
  },
});
