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
