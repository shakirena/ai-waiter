import { render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it } from "vitest";

import App from "./App";

function renderAt(path: string) {
  render(
    <MemoryRouter initialEntries={[path]}>
      <App />
    </MemoryRouter>,
  );
}

describe("Маршруты приложения", () => {
  it.each([
    ["/t/demo", "guest-page", "Гость"],
    ["/t/demo/menu", "guest-page", "Гость"],
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

  it("страница гостя показывает токен стола из адреса", async () => {
    renderAt("/t/abc123");
    expect(await screen.findByTestId("guest-table-token")).toHaveTextContent("abc123");
  });

  it.each(["/", "/unknown", "/t", "/staffroom"])("%s показывает «Страница не найдена»", (path) => {
    renderAt(path);
    expect(screen.getByTestId("not-found-page")).toBeInTheDocument();
    expect(screen.getByText("Страница не найдена")).toBeInTheDocument();
  });
});
