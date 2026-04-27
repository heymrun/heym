import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
import fs from "fs";
import path from "path";

const apiTarget = process.env.VITE_API_TARGET || "http://localhost:10105";

const getVersion = (): string => {
  try {
    const versionPath = path.resolve(process.cwd(), "VERSION");
    return fs.readFileSync(versionPath, "utf-8").trim();
  } catch {
    return "0.1.0";
  }
};

const APP_VERSION = process.env.APP_VERSION || getVersion();

const apiProxyOptions = {
  target: apiTarget,
  changeOrigin: true,
  ws: true,
  configure: (proxy: any) => {
    proxy.on("proxyReq", (proxyReq: any, req: any) => {
      if (req.headers["cf-connecting-ip"]) {
        proxyReq.setHeader("CF-Connecting-IP", req.headers["cf-connecting-ip"]);
      }
      if (req.headers["x-forwarded-for"]) {
        proxyReq.setHeader("X-Forwarded-For", req.headers["x-forwarded-for"]);
      }
    });
    proxy.on("proxyRes", (proxyRes: any) => {
      delete proxyRes.headers["transfer-encoding"];
    });
  },
};

const proxyConfig = {
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
