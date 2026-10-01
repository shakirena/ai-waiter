import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

// В конфигурации globals: false, поэтому Testing Library не регистрирует
// автоочистку сама — размонтируем отрендеренное после каждого теста явно.
afterEach(() => {
  cleanup();
});
