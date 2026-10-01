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

export async function getHealth(signal?: AbortSignal): Promise<HealthResponse> {
  void signal;
  throw new Error("not implemented");
}
