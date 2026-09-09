import { fileURLToPath, URL } from "node:url";

import { defineConfig } from "vite";
import vue from "@vitejs/plugin-vue";

// 构建产物由 FastAPI 的 StaticFiles 伺服（server/app.py 指向 frontend/dist）。
// base: "./" 让 dist 既能在 / 根路径伺服，也能被 pywebview 以 file:// 加载。
// 后端地址：默认与 main.py 默认端口一致（8044）；可用 XIUXIAN_BACKEND 覆盖
const BACKEND = process.env.XIUXIAN_BACKEND || "http://127.0.0.1:8044";

export default defineConfig({
  plugins: [vue()],
  base: "./",
  resolve: {
    // 与 tsconfig paths 保持一致：@/ → src/
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
    // 单机本地伺服，不做 CDN/分包优化；保持产物简单可读
    sourcemap: false,
    chunkSizeWarningLimit: 1200,
  },
  server: {
    port: 5173,
    // 开发期把 /api 与 /health 代理到本地 FastAPI（生产由 FastAPI 直接伺服 dist）
    proxy: {
      "/api": { target: BACKEND, changeOrigin: true },
      "/health": { target: BACKEND, changeOrigin: true },
    },
  },
});
