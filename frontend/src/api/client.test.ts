import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, getHealth } from "./client";
import type { HealthResponse } from "./types";

// Сеть не используется: глобальный fetch подменяется моком в каждом тесте.
const fetchMock = vi.fn<typeof fetch>();

function jsonResponse(body: unknown, status = 200): Response {
  return new Response(JSON.stringify(body), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}

beforeEach(() => {
  vi.stubGlobal("fetch", fetchMock);
});

afterEach(() => {
  fetchMock.mockReset();
  vi.unstubAllGlobals();
});

describe("getHealth", () => {
  it("запрашивает относительный /health и возвращает тело ответа", async () => {
    const body: HealthResponse = { status: "ok", mode: "single", version: "0.1.0" };
    fetchMock.mockResolvedValueOnce(jsonResponse(body));

    await expect(getHealth()).resolves.toEqual(body);

    expect(fetchMock).toHaveBeenCalledTimes(1);
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/health");
    expect(init?.method).toBe("GET");
    expect(init?.headers).toEqual({ Accept: "application/json" });
  });

  it("передаёт AbortSignal в fetch", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ status: "ok", mode: "scaled", version: "0.1.0" }));
    const controller = new AbortController();

    await getHealth(controller.signal);

    expect(fetchMock.mock.calls[0]![1]?.signal).toBe(controller.signal);
  });

  it("при ответе не 2xx выбрасывает ApiError с кодом", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: "unavailable" }, 503));

    const error = await getHealth().catch((e: unknown) => e);

    expect(error).toBeInstanceOf(ApiError);
    expect((error as ApiError).status).toBe(503);
    expect((error as ApiError).name).toBe("ApiError");
  });

  it("пробрасывает сетевую ошибку fetch", async () => {
    fetchMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    await expect(getHealth()).rejects.toThrow("Failed to fetch");
  });
});
