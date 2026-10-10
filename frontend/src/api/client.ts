import type { HealthResponse } from "./types";

// Все запросы — относительные пути (same-origin, ADR-3): без адресов и CORS.

export class ApiError extends Error {
  constructor(
    public readonly status: number,
    message: string,
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
