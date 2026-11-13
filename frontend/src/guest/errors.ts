import { ApiError } from "../api/client";
import type { MessageKey } from "./i18n";

// Что показать гостю на ошибку API (FR-11 spec #9, ADR-9.6). На экран не попадают
// код ошибки, токен и технические подробности — только текст по виду ошибки.
export type GuestErrorKind = "qr_invalid" | "table_inactive" | "rate_limited" | "visit_closed" | "unavailable";

export const ERROR_MESSAGE: Record<GuestErrorKind, MessageKey> = {
  qr_invalid: "errorQrInvalid",
  table_inactive: "errorTableInactive",
  rate_limited: "errorRateLimited",
  visit_closed: "errorVisitClosed",
  unavailable: "errorUnavailable",
};

/** Ошибка входа `POST /entry` → вид экрана ошибки. */
export function entryErrorKind(error: unknown): GuestErrorKind {
  if (!(error instanceof ApiError)) return "unavailable"; // сеть, обрыв, битый JSON ответа
  switch (error.code) {
    case "qr_invalid":
    case "table_inactive":
    case "rate_limited":
    case "visit_closed":
      return error.code;
    default:
      break;
  }
  // 422 без кода — токен из адреса не прошёл валидацию тела (пустой или длиннее 128 символов):
  // для гостя это тот же недействительный QR (E-4 spec).
  if (error.status === 422 && error.code === null) return "qr_invalid";
  return "unavailable"; // 5xx, 503 try_again и прочее неожиданное
}

/** Сессия потеряна, но токен из адреса действует — фронтенд сам входит заново (FR-6 spec). */
export function needsSilentReentry(error: unknown): boolean {
  return (
    error instanceof ApiError &&
    (error.code === "guest_session_required" || error.code === "guest_session_invalid")
  );
}

export function isVisitClosed(error: unknown): boolean {
  return error instanceof ApiError && error.code === "visit_closed";
}
