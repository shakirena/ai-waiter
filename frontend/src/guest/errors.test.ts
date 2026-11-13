import { describe, expect, it } from "vitest";

import { ApiError } from "../api/client";
import type { ApiErrorCode } from "../api/types";
import { entryErrorKind, isVisitClosed, needsSilentReentry } from "./errors";

const apiError = (status: number, code: ApiErrorCode | null = null) => new ApiError(status, "ошибка", code);

describe("entryErrorKind — ошибка входа → экран (FR-11 spec #9)", () => {
  it.each([
    [apiError(404, "qr_invalid"), "qr_invalid"],
    [apiError(403, "table_inactive"), "table_inactive"],
    [apiError(429, "rate_limited"), "rate_limited"],
    [apiError(401, "visit_closed"), "visit_closed"],
    [apiError(422), "qr_invalid"],
    [apiError(422, "lang_not_supported"), "unavailable"],
    [apiError(503, "try_again"), "unavailable"],
    [apiError(500), "unavailable"],
    [apiError(502), "unavailable"],
    [apiError(404), "unavailable"],
    [apiError(401, "guest_session_required"), "unavailable"],
    [new TypeError("Failed to fetch"), "unavailable"],
    [new SyntaxError("Unexpected token"), "unavailable"],
    ["строка", "unavailable"],
  ])("%o → %s", (error, expected) => {
    expect(entryErrorKind(error)).toBe(expected);
  });
});

describe("needsSilentReentry", () => {
  it.each([
    [apiError(401, "guest_session_required"), true],
    [apiError(401, "guest_session_invalid"), true],
    [apiError(401, "visit_closed"), false],
    [apiError(401), false],
    [new TypeError("Failed to fetch"), false],
  ])("%o → %s", (error, expected) => {
    expect(needsSilentReentry(error)).toBe(expected);
  });
});

describe("isVisitClosed", () => {
  it.each([
    [apiError(401, "visit_closed"), true],
    [apiError(401, "guest_session_invalid"), false],
    [new Error("visit_closed"), false],
  ])("%o → %s", (error, expected) => {
    expect(isVisitClosed(error)).toBe(expected);
  });
});
