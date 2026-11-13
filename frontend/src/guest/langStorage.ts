import type { GuestLang } from "../api/types";
import { isGuestLang } from "./i18n";

// Явный выбор языка на устройстве (FR-7 шаг 1, FR-11 spec #9). Хранилище может быть
// недоступно (приватный режим, запрет cookies сайта) — тогда выбор просто не запоминается.
export const LANG_STORAGE_KEY = "aiw_guest_lang";

export function readStoredLang(): GuestLang | null {
  try {
    const value = window.localStorage.getItem(LANG_STORAGE_KEY);
    return isGuestLang(value) ? value : null;
  } catch {
    return null;
  }
}

export function writeStoredLang(lang: GuestLang): void {
  try {
    window.localStorage.setItem(LANG_STORAGE_KEY, lang);
  } catch {
    // Хранилище недоступно: язык остаётся в сессии сервера до конца визита.
  }
}
