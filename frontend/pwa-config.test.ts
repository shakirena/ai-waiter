// @vitest-environment node
import { mkdtemp, readFile, readdir, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { build, resolveConfig } from "vite";
import { afterAll, beforeAll, describe, expect, it } from "vitest";

// AC-5 (#41): настоящая сборка во временный каталог (dist не трогается): манифест PWA,
// service worker и границы с backend. Тест не зависит от порядка npm run build.
interface Manifest {
  name: string;
  start_url: string;
  display: string;
  icons: { src: string; sizes: string; type: string; purpose: string }[];
}

let outDir = "";
let files: string[] = [];

beforeAll(async () => {
  outDir = await mkdtemp(join(tmpdir(), "ai-waiter-pwa-"));
  await build({
    configFile: "./vite.config.ts",
    mode: "test",
    logLevel: "silent",
    build: { outDir, emptyOutDir: true, sourcemap: false },
  });
  files = await readdir(outDir);
}, 60_000);

afterAll(async () => {
  if (outDir) await rm(outDir, { recursive: true, force: true });
});

describe("сборка: PWA", () => {
  it("манифест: name, start_url, display standalone, иконки 192 и 512", async () => {
    expect(files).toContain("manifest.webmanifest");
    const manifest = JSON.parse(await readFile(join(outDir, "manifest.webmanifest"), "utf8")) as Manifest;
    expect(manifest.name).toBe("AI Waiter");
    expect(manifest.start_url).toBe("/");
    expect(manifest.display).toBe("standalone");
    expect(new Set(manifest.icons.map((i) => i.sizes))).toEqual(new Set(["192x192", "512x512"]));
    expect(manifest.icons.some((i) => i.purpose === "maskable")).toBe(true);
  });

  it("есть service worker и скрипт его регистрации", () => {
    expect(files).toContain("sw.js");
    expect(files).toContain("registerSW.js");
  });

  it("service worker не перехватывает API, Integration API и /health, но отдаёт SPA для экранов", async () => {
    const sw = await readFile(join(outDir, "sw.js"), "utf8");
    expect(sw).toContain("NavigationRoute");
    expect(sw).toContain("/index.html");
    // denylist передаётся в NavigationRoute как массив регулярных выражений /^\/префикс(\/|$)/
    for (const prefix of ["api", "integration", "health", "ws"]) {
      expect(sw, prefix).toContain(`/^\\/${prefix}(\\/|$)/`);
    }
  });
});

describe("конфигурация: dev server", () => {
  it("проксирует пути backend и только их", async () => {
    const resolved = await resolveConfig({ configFile: "./vite.config.ts", mode: "test" }, "serve");
    expect(Object.keys(resolved.server.proxy ?? {}).sort()).toEqual(
      ["/api", "/docs", "/health", "/integration", "/openapi.json", "/redoc", "/ws"].sort(),
    );
  });
});
