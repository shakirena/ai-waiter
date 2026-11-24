import { afterEach, describe, expect, it, vi } from "vitest";

import { browserLang, isGuestLang, langFromTag, translate, type MessageKey } from "./i18n";

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("langFromTag — язык экрана по тегу браузера (R-Q2)", () => {
  it.each([
    ["az", "az"],
    ["az-AZ", "az"],
    ["az-Latn-AZ", "az"],
    ["AZ_az", "az"],
    ["ru", "ru"],
    ["ru-RU", "ru"],
    [" RU-ru ", "ru"],
    ["en-US", "az"],
    ["tr", "az"],
    ["", "az"],
    ["*", "az"],
    [null, "az"],
    [undefined, "az"],
  ])("%j → %s", (tag, expected) => {
    expect(langFromTag(tag)).toBe(expected);
  });
});

describe("browserLang", () => {
  it("берёт navigator.language", () => {
    vi.stubGlobal("navigator", { language: "ru-RU" });
    expect(browserLang()).toBe("ru");
  });

  it("браузер не az/ru → az", () => {
    vi.stubGlobal("navigator", { language: "en-GB" });
    expect(browserLang()).toBe("az");
  });

  it("без navigator → az", () => {
    vi.stubGlobal("navigator", undefined);
    expect(browserLang()).toBe("az");
  });
});

describe("isGuestLang", () => {
  it.each([
    ["az", true],
    ["ru", true],
    ["en", false],
    ["", false],
    [null, false],
    [1, false],
  ])("%j → %s", (value, expected) => {
    expect(isGuestLang(value)).toBe(expected);
  });
});

describe("translate", () => {
  const keys: MessageKey[] = [
    "loading",
    "welcome",
    "yourTable",
    "yourCabin",
    "comingSoon",
    "langSwitchLabel",
    "langChangeFailed",
    "errorQrInvalid",
    "errorTableInactive",
    "errorRateLimited",
    "errorVisitClosed",
    "errorUnavailable",
    "restart",
    "retry",
  ];

  it.each(keys)("ключ %s есть на обоих языках и тексты различаются", (key) => {
    expect(translate("az", key)).not.toBe("");
    expect(translate("ru", key)).not.toBe("");
    expect(translate("az", key)).not.toBe(translate("ru", key));
  });

  it("тексты ошибок RU — по решению пользователя ADR-9.6", () => {
    expect(translate("ru", "errorQrInvalid")).toBe("QR-код недействителен, обратитесь к официанту");
    expect(translate("ru", "errorTableInactive")).toBe("Стол временно не обслуживается, обратитесь к официанту");
    expect(translate("ru", "errorRateLimited")).toBe("Слишком много попыток, повторите через минуту");
    expect(translate("ru", "errorVisitClosed")).toBe("Визит завершён");
    expect(translate("ru", "restart")).toBe("Начать заново");
    expect(translate("ru", "errorUnavailable")).toBe("Сервис временно недоступен");
    expect(translate("ru", "retry")).toBe("Повторить");
  });
});
