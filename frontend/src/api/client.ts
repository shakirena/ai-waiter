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

// Известные коды ошибок API. Record по ApiErrorCode — компилятор требует перечислить все коды,
// поэтому новый код в types.ts без правки здесь не соберётся.
const KNOWN_ERROR_CODES: Record<ApiErrorCode, true> = {
  qr_invalid: true,
  table_inactive: true,
  rate_limited: true,
  try_again: true,
  guest_session_required: true,
  guest_session_invalid: true,
  visit_closed: true,
  lang_not_supported: true,
};

function isApiErrorCode(value: unknown): value is ApiErrorCode {
  return typeof value === "string" && Object.hasOwn(KNOWN_ERROR_CODES, value);
}

/** Код ошибки из тела `{"detail": {"code": "..."}}` (DEC-015); иначе null. */
async function readErrorCode(response: Response): Promise<ApiErrorCode | null> {
  let body: unknown;
  try {
    body = await response.json();
  } catch {
    return null;
  }
  if (typeof body !== "object" || body === null) return null;
  const detail = (body as { detail?: unknown }).detail;
  if (typeof detail !== "object" || detail === null || Array.isArray(detail)) return null;
  const code = (detail as { code?: unknown }).code;
  return isApiErrorCode(code) ? code : null;
}

interface RequestOptions {
  body?: unknown;
  signal?: AbortSignal;
}

async function requestJson<T>(method: "GET" | "POST" | "PUT", path: string, options: RequestOptions = {}): Promise<T> {
  const { body, signal } = options;
  const init: RequestInit = { method, headers: { Accept: "application/json" }, signal };
  if (body !== undefined) {
    // Изменяющие запросы гостя принимают только JSON-тело (NFR-5 spec #9).
    init.headers = { Accept: "application/json", "Content-Type": "application/json" };
    init.body = JSON.stringify(body);
  }
  const response = await fetch(path, init);
  if (!response.ok) {
    const code = await readErrorCode(response);
    throw new ApiError(response.status, `Запрос ${path} завершился с кодом ${response.status}`, code);
  }
  return (await response.json()) as T;
}

/** Liveness-проверка backend-а: `GET /health`. */
export function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  return requestJson<HealthResponse>("GET", "/health", { signal });
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
  return requestJson<GuestEntryResponse>("POST", "/api/guest/v1/entry", { body: { token, lang }, signal });
}

/** Данные действующей сессии: `GET /api/guest/v1/session` (401 — см. ApiError.code). */
export function getGuestSession(signal?: AbortSignal): Promise<GuestSessionResponse> {
  return requestJson<GuestSessionResponse>("GET", "/api/guest/v1/session", { signal });
}

/** Смена языка устройства: `PUT /api/guest/v1/session/lang` с телом `{lang}` (ADR-9.4). */
export function setGuestLang(lang: GuestLang, signal?: AbortSignal): Promise<GuestSessionResponse> {
  return requestJson<GuestSessionResponse>("PUT", "/api/guest/v1/session/lang", { body: { lang }, signal });
}
