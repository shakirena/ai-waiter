import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LANG_STORAGE_KEY, readStoredLang, writeStoredLang } from "./langStorage";

beforeEach(() => {
  window.localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  window.localStorage.clear();
});

describe("язык устройства в localStorage", () => {
  it("пусто → null", () => {
    expect(readStoredLang()).toBeNull();
  });

  it("записанный язык читается обратно", () => {
    writeStoredLang("ru");
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBe("ru");
    expect(readStoredLang()).toBe("ru");
  });

  it("постороннее значение → null", () => {
    window.localStorage.setItem(LANG_STORAGE_KEY, "en");
    expect(readStoredLang()).toBeNull();
  });

  it("чтение из недоступного хранилища → null без исключения", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => {
      throw new DOMException("denied", "SecurityError");
    });
    expect(readStoredLang()).toBeNull();
  });

  it("запись в недоступное хранилище не бросает исключение", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => {
      throw new DOMException("quota", "QuotaExceededError");
    });
    expect(() => writeStoredLang("az")).not.toThrow();
  });
});
