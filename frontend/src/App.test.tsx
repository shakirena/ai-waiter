import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

// Страница гостя при монтировании входит по токену (POST /api/guest/v1/entry): сеть не нужна,
// fetch подменяется запросом, который не завершается, — проверяется только маршрут.
const fetchMock = vi.fn<typeof fetch>(() => new Promise<Response>(() => {}));

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  fetchMock.mockClear();
  vi.unstubAllGlobals();
});

describe("Маршруты приложения", () => {
  it.each(["/t/demo", "/t/demo/menu"])("%s лениво загружает экран гостя и входит по токену", async (path) => {
    renderAt(path);
    expect(await screen.findByTestId("guest-page")).toBeInTheDocument();
    expect(screen.getByTestId("guest-loading")).toBeInTheDocument();
    expect(fetchMock).toHaveBeenCalledWith("/api/guest/v1/entry", expect.objectContaining({ method: "POST" }));
    expect(JSON.parse(fetchMock.mock.calls[0]![1]!.body as string)).toMatchObject({ token: "demo" });
  });

  it.each([
    ["/staff", "staff-page", "Официант"],
    ["/staff/orders", "staff-page", "Официант"],
    ["/admin", "admin-page", "Админка"],
    ["/admin/menu", "admin-page", "Админка"],
  ])("%s лениво загружает заглушку %s", async (path, testId, title) => {
    renderAt(path);
    // Страницы подгружаются через React.lazy — ждём появления после Suspense.
    const page = await screen.findByTestId(testId);
    expect(page).toBeInTheDocument();
    expect(screen.getByTestId(`${testId}-title`)).toHaveTextContent(title);
    expect(screen.queryByTestId("page-loading")).not.toBeInTheDocument();
  });

  it.each(["/", "/unknown", "/t", "/staffroom"])("%s показывает «Страница не найдена»", (path) => {
    renderAt(path);
    expect(screen.getByTestId("not-found-page")).toBeInTheDocument();
    expect(screen.getByText("Страница не найдена")).toBeInTheDocument();
  });
});
