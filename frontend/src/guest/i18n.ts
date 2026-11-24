import type { GuestLang } from "../api/types";

// Минимальный словарь экрана гостя #9 (FR-11 spec). Полная i18n интерфейса гостя — #13.
// Азербайджанские тексты до запуска проверяет носитель языка (ТЗ AI-6).

export const GUEST_LANGS: readonly GuestLang[] = ["az", "ru"];

// Язык экрана, когда заведение ещё неизвестно и браузер не az/ru (R-Q2 spec).
export const FALLBACK_LANG: GuestLang = "az";

const ru = {
  loading: "Загрузка…",
  welcome: "Добро пожаловать!",
  yourTable: "Ваш стол",
  yourCabin: "Ваша кабина",
  comingSoon: "Скоро здесь появятся меню и чат с официантом.",
  langSwitchLabel: "Язык",
  langChangeFailed: "Не удалось сменить язык, попробуйте ещё раз.",
  errorQrInvalid: "QR-код недействителен, обратитесь к официанту",
  errorTableInactive: "Стол временно не обслуживается, обратитесь к официанту",
  errorRateLimited: "Слишком много попыток, повторите через минуту",
  errorVisitClosed: "Визит завершён",
  errorUnavailable: "Сервис временно недоступен",
  restart: "Начать заново",
  retry: "Повторить",
};

export type MessageKey = keyof typeof ru;

const az: Record<MessageKey, string> = {
  loading: "Yüklənir…",
  welcome: "Xoş gəlmisiniz!",
  yourTable: "Masanız",
  yourCabin: "Kabinəniz",
  comingSoon: "Tezliklə burada menyu və ofisiantla çat olacaq.",
  langSwitchLabel: "Dil",
  langChangeFailed: "Dili dəyişmək alınmadı, yenidən cəhd edin.",
  errorQrInvalid: "QR-kod etibarsızdır, ofisianta müraciət edin",
  errorTableInactive: "Masa müvəqqəti olaraq xidmət göstərmir, ofisianta müraciət edin",
  errorRateLimited: "Həddindən çox cəhd edildi, bir dəqiqədən sonra yenidən cəhd edin",
  errorVisitClosed: "Ziyarət başa çatıb",
  errorUnavailable: "Xidmət müvəqqəti olaraq əlçatan deyil",
  restart: "Yenidən başla",
  retry: "Yenidən cəhd et",
};

const MESSAGES: Record<GuestLang, Record<MessageKey, string>> = { az, ru };

// Название языка на нём самом — подпись кнопки переключателя для экранных чтецов.
export const LANG_NATIVE_NAMES: Record<GuestLang, string> = {
  az: "Azərbaycan dili",
  ru: "Русский язык",
};

export function translate(lang: GuestLang, key: MessageKey): string {
  return MESSAGES[lang][key];
}

export function isGuestLang(value: unknown): value is GuestLang {
  return typeof value === "string" && (GUEST_LANGS as readonly string[]).includes(value);
}

/**
 * Язык по тегу браузера: основной подтег (`az-Latn-AZ` → `az`, `ru-RU` → `ru`), иначе `az` (R-Q2).
 * Используется, пока заведение и язык сессии неизвестны (загрузка, ошибка входа).
 */
export function langFromTag(tag: string | null | undefined): GuestLang {
  const primary = (tag ?? "").trim().split(/[-_]/, 1)[0]?.toLowerCase();
  return isGuestLang(primary) ? primary : FALLBACK_LANG;
}

export function browserLang(): GuestLang {
  return langFromTag(typeof navigator === "undefined" ? null : navigator.language);
}
