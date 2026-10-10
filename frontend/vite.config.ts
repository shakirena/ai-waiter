/// <reference types="vitest/config" />
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig, loadEnv } from "vite";
import { VitePWA } from "vite-plugin-pwa";

// Должен совпадать с RESERVED_PREFIXES в backend/app/web/spa.py (ADR-3).
const BACKEND_PREFIXES = ["/api", "/integration", "/health", "/ws", "/docs", "/redoc", "/openapi.json"];

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  // Адрес backend-а только для dev server; в сборку не попадает.
  const apiTarget = env.VITE_API_PROXY_TARGET || "http://localhost:8000";

  return {
    plugins: [
      react(),
      tailwindcss(),
      VitePWA({
        registerType: "autoUpdate",
        injectRegister: "auto",
        includeAssets: ["icons/*.png"],
        manifest: {
          name: "AI Waiter",
          short_name: "AI Waiter",
          description: "Меню и заказ за столом",
          lang: "ru",
          start_url: "/",
          scope: "/",
          display: "standalone",
          background_color: "#ffffff",
          theme_color: "#111827",
          // Иконки генерирует scripts/generate-icons.mjs (npm run icons). Фон залит theme_color,
          // знак лежит в безопасной зоне maskable (круг 80%), поэтому файлы годятся для обеих целей.
          icons: [
            { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "any" },
            { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "any" },
            { src: "/icons/icon-192.png", sizes: "192x192", type: "image/png", purpose: "maskable" },
            { src: "/icons/icon-512.png", sizes: "512x512", type: "image/png", purpose: "maskable" },
          ],
        },
        workbox: {
          navigateFallback: "/index.html",
          // Service Worker не перехватывает API, Integration API, SSE и WebSocket.
          navigateFallbackDenylist: BACKEND_PREFIXES.map((p) => new RegExp(`^${escapeRe(p)}(/|$)`)),
          runtimeCaching: [],
        },
      }),
    ],
    server: {
      port: 5173,
      proxy: Object.fromEntries(
        BACKEND_PREFIXES.map((p) => [p, { target: apiTarget, changeOrigin: false, ws: p === "/ws" }]),
      ),
    },
    build: {
      outDir: "dist",
      sourcemap: true,
    },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      globals: false,
      coverage: {
        provider: "v8",
        include: ["src/**/*.{ts,tsx}"],
        exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/**/*.d.ts", "src/api/types.ts"], // types.ts — только типы, кода нет
        reporter: ["text"],
      },
    },
  };
});
