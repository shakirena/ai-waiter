// Типы ответов API. Соответствуют Pydantic-схемам backend/app/api/health.py.
// Соглашения API: деньги — строка "12.50", время — ISO 8601 с зоной.

export type AppMode = "single" | "scaled";

export interface HealthResponse {
  status: "ok";
  mode: AppMode;
  version: string;
}

export type CheckStatus = "ok" | "fail" | "skipped";

export interface ReadinessResponse {
  status: "ready" | "not_ready";
  checks: Record<"database" | "redis", CheckStatus>;
}

// --- Гостевой API /api/guest/v1 (#9, docs/arch/feature-9-guest-qr-entry.md, backend/app/schemas/guest.py)

export type GuestLang = "az" | "ru";

export type TableType = "table" | "cabin";

export interface GuestTenant {
  name: string;
  languages: GuestLang[];
  default_lang: GuestLang;
  currency: string;
}

export interface GuestTable {
  name: string;
  type: TableType;
}

export interface GuestVisit {
  id: string;
  opened_at: string;
}

export interface GuestSessionResponse {
  tenant: GuestTenant;
  table: GuestTable;
  visit: GuestVisit;
  lang: GuestLang;
}

export interface GuestEntryResponse extends Omit<GuestSessionResponse, "visit"> {
  visit: GuestVisit & { is_new: boolean };
}

// Коды ошибок API (ADR-9.6); текст фронтенд локализует по коду.
export type ApiErrorCode =
  | "qr_invalid"
  | "table_inactive"
  | "rate_limited"
  | "try_again"
  | "guest_session_required"
  | "guest_session_invalid"
  | "visit_closed"
  | "lang_not_supported";

// Тело ошибки /api/*: {"detail": {"code": "..."}}. 422 валидации тела — {"detail": [...]}.
export interface ApiErrorBody {
  detail: { code: ApiErrorCode };
}
