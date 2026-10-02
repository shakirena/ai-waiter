import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

// Точка входа: монтирует приложение в #root внутри BrowserRouter либо падает с понятной ошибкой.
describe("main.tsx", () => {
  beforeEach(() => {
    vi.resetModules();
    document.body.innerHTML = "";
    window.history.pushState({}, "", "/nonexistent-qa-route");
  });

  afterEach(() => {
    document.body.innerHTML = "";
  });

  it("монтирует приложение в #root", async () => {
    const root = document.createElement("div");
    root.id = "root";
    document.body.appendChild(root);

    await import("./main");

    await vi.waitFor(() => {
      expect(root.childElementCount).toBeGreaterThan(0);
    });
  });

  it("без элемента #root выбрасывает понятную ошибку", async () => {
    await expect(import("./main")).rejects.toThrow("Элемент #root не найден");
  });
});
