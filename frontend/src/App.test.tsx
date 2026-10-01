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
    ["/t/abc123", "Гость"],
    ["/staff", "Официант"],
    ["/admin", "Админка"],
    ["/unknown", "Страница не найдена"],
  ])("%s показывает «%s»", (path, text) => {
    renderAt(path);
    expect(screen.getByText(text)).toBeInTheDocument();
  });
});
