import type {
  ApiErrorCode,
  GuestEntryResponse,
  GuestLang,
  GuestSessionResponse,
  HealthResponse,
} from "./types";

// Все запросы — относительные пути (same-origin, ADR-3): без адресов и CORS.

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
    // Код из тела {"detail": {"code": "..."}} (ADR-9.6, #9); null — тела с кодом нет (в т. ч. 422 валидации).
    public readonly code: ApiErrorCode | null = null,
  ) {
    super(message);
    this.name = "ApiError";
  }
}

async function getJson<T>(path: string, signal?: AbortSignal): Promise<T> {
  const response = await fetch(path, {
    method: "GET",
    headers: { Accept: "application/json" },
    signal,
  });
  if (!response.ok) {
    throw new ApiError(response.status, `Запрос ${path} завершился с кодом ${response.status}`);
  }
  return (await response.json()) as T;
}

/** Liveness-проверка backend-а: `GET /health`. */
export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return getJson<HealthResponse>("/health", signal);
}

// --- Гостевой API /api/guest/v1 (#9). Cookie сессии HttpOnly ставит сервер (same-origin fetch
// отправляет её сам, credentials: "same-origin" по умолчанию). Ошибка — ApiError с code из тела.

/**
 * Вход по QR-токену: `POST /api/guest/v1/entry` с телом `{token, lang}` (ADR-9.1).
 * `lang` — явный выбор устройства из localStorage или null.
 */
export function enterTable(
  token: string,
  lang: GuestLang | null,
  signal?: AbortSignal,
): Promise<GuestEntryResponse> {
  void token;
  void lang;
  void signal;
  throw new Error("not implemented");
}

/** Данные действующей сессии: `GET /api/guest/v1/session` (401 — см. ApiError.code). */
export function getGuestSession(signal?: AbortSignal): Promise<GuestSessionResponse> {
  void signal;
  throw new Error("not implemented");
}

/** Смена языка устройства: `PUT /api/guest/v1/session/lang` с телом `{lang}` (ADR-9.4). */
export function setGuestLang(lang: GuestLang, signal?: AbortSignal): Promise<GuestSessionResponse> {
  void lang;
  void signal;
  throw new Error("not implemented");
}
