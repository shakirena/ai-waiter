import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, enterTable, getGuestSession, getHealth, setGuestLang } from "./client";
import type { GuestEntryResponse, HealthResponse } from "./types";

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

const entryBody: GuestEntryResponse = {
  tenant: { name: "Демо-ресторан", languages: ["az", "ru"], default_lang: "az", currency: "AZN" },
  table: { name: "Стол 1", type: "table" },
  visit: { id: "0192-visit", opened_at: "2026-11-04T18:05:00+04:00", is_new: true },
  lang: "ru",
};

function errorOf(promise: Promise<unknown>): Promise<ApiError> {
  return promise.then(
    () => {
      throw new Error("ожидалась ошибка");
    },
    (e: unknown) => e as ApiError,
  );
}

describe("enterTable", () => {
  it("POST /api/guest/v1/entry с JSON-телом {token, lang}", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(entryBody));
    const controller = new AbortController();

    await expect(enterTable("tok_123", "ru", controller.signal)).resolves.toEqual(entryBody);

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/guest/v1/entry");
    expect(init?.method).toBe("POST");
    expect(init?.headers).toEqual({ Accept: "application/json", "Content-Type": "application/json" });
    expect(JSON.parse(init?.body as string)).toEqual({ token: "tok_123", lang: "ru" });
    expect(init?.signal).toBe(controller.signal);
  });

  it("передаёт lang: null, если выбора на устройстве нет", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse(entryBody));

    await enterTable("tok_123", null);

    expect(JSON.parse(fetchMock.mock.calls[0]![1]?.body as string)).toEqual({ token: "tok_123", lang: null });
  });

  it.each([
    [404, "qr_invalid"],
    [403, "table_inactive"],
    [429, "rate_limited"],
    [503, "try_again"],
  ] as const)("ответ %i {detail: {code: %s}} → ApiError с кодом", async (status, code) => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: { code } }, status));

    const error = await errorOf(enterTable("tok", null));

    expect(error).toBeInstanceOf(ApiError);
    expect(error.status).toBe(status);
    expect(error.code).toBe(code);
  });

  it.each([
    ["422 валидации — массив detail", { detail: [{ loc: ["body", "token"], msg: "too long" }] }],
    ["неизвестный код", { detail: { code: "something_new" } }],
    ["detail-строка", { detail: "Not Found" }],
    ["код не строка", { detail: { code: 42 } }],
    ["тело не объект", "oops"],
    ["тело null", null],
  ])("%s → ApiError без кода", async (_name, body) => {
    fetchMock.mockResolvedValueOnce(jsonResponse(body, 422));

    const error = await errorOf(enterTable("tok", null));

    expect(error.status).toBe(422);
    expect(error.code).toBeNull();
  });

  it("тело ошибки не JSON → ApiError без кода", async () => {
    fetchMock.mockResolvedValueOnce(new Response("<html>Bad Gateway</html>", { status: 502 }));

    const error = await errorOf(enterTable("tok", null));

    expect(error.status).toBe(502);
    expect(error.code).toBeNull();
  });

  it("сообщение ошибки не содержит токен и тело запроса", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: { code: "qr_invalid" } }, 404));

    const error = await errorOf(enterTable("secret_token_value", null));

    expect(error.message).not.toContain("secret_token_value");
  });
});

describe("getGuestSession", () => {
  it("GET /api/guest/v1/session без тела", async () => {
    const { visit, ...rest } = entryBody;
    const body = { ...rest, visit: { id: visit.id, opened_at: visit.opened_at } };
    fetchMock.mockResolvedValueOnce(jsonResponse(body));

    await expect(getGuestSession()).resolves.toEqual(body);

    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/guest/v1/session");
    expect(init?.method).toBe("GET");
    expect(init?.body).toBeUndefined();
  });

  it("401 visit_closed → ApiError с кодом", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ detail: { code: "visit_closed" } }, 401));

    const error = await errorOf(getGuestSession());

    expect(error.code).toBe("visit_closed");
  });
});

describe("setGuestLang", () => {
  it("PUT /api/guest/v1/session/lang с JSON-телом {lang}", async () => {
    fetchMock.mockResolvedValueOnce(jsonResponse({ ...entryBody, lang: "az" }));

    const result = await setGuestLang("az");

    expect(result.lang).toBe("az");
    const [url, init] = fetchMock.mock.calls[0]!;
    expect(url).toBe("/api/guest/v1/session/lang");
    expect(init?.method).toBe("PUT");
    expect(init?.headers).toEqual({ Accept: "application/json", "Content-Type": "application/json" });
    expect(JSON.parse(init?.body as string)).toEqual({ lang: "az" });
  });

  it.each(["guest_session_required", "guest_session_invalid", "lang_not_supported"] as const)(
    "ошибка %s → ApiError с кодом",
    async (code) => {
      fetchMock.mockResolvedValueOnce(jsonResponse({ detail: { code } }, code === "lang_not_supported" ? 422 : 401));

      const error = await errorOf(setGuestLang("ru"));

      expect(error.code).toBe(code);
    },
  );
});
