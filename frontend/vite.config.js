/* eslint-env node */
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";
import { defineConfig } from "vite";
var apiTarget = process.env.VITE_API_TARGET || "http://localhost:10105";
var apiProxyOptions = {
    target: apiTarget,
    changeOrigin: true,
    ws: true,
    configure: function (proxy) {
        proxy.on("proxyReq", function (proxyReq, req) {
            if (req.headers["cf-connecting-ip"]) {
                proxyReq.setHeader("CF-Connecting-IP", req.headers["cf-connecting-ip"]);
            }
            if (req.headers["x-forwarded-for"]) {
                proxyReq.setHeader("X-Forwarded-For", req.headers["x-forwarded-for"]);
            }
        });
        proxy.on("proxyRes", function (proxyRes) {
            delete proxyRes.headers["transfer-encoding"];
        });
    },
};
var proxyConfig = {
    "/api": apiProxyOptions,
    "/.well-known/oauth-authorization-server": apiProxyOptions,
    "/authorize": apiProxyOptions,
    "/token": apiProxyOptions,
    "/register": apiProxyOptions,
};
export default defineConfig({
    plugins: [vue()],
    resolve: {
        alias: {
            "@": fileURLToPath(new URL("./src", import.meta.url)),
        },
    },
    server: {
        port: 4017,
        host: "0.0.0.0",
        proxy: proxyConfig,
    },
    preview: {
        port: 4017,
        host: "0.0.0.0",
        allowedHosts: true,
        proxy: proxyConfig,
    },
});
