import type { GuestLang } from "../api/types";
import { LANG_NATIVE_NAMES, translate } from "./i18n";

interface LanguageSwitcherProps {
  /** Языки заведения из ответа входа, в его порядке. */
  languages: readonly GuestLang[];
  current: GuestLang;
  /** Язык, на который идёт переключение; пока запрос не завершён, кнопки неактивны. */
  pending: GuestLang | null;
  onChange: (lang: GuestLang) => void;
}

// Переключатель AZ/RU (#86, FR-11 spec). При одном языке заведения не показывается (E-13).
export function LanguageSwitcher({ languages, current, pending, onChange }: LanguageSwitcherProps) {
  if (languages.length < 2) return null;

  return (
    <div
      role="group"
      aria-label={translate(current, "langSwitchLabel")}
      data-testid="guest-lang-switch"
      className="inline-flex shrink-0 rounded-full border border-gray-300 p-0.5"
    >
      {languages.map((lang) => {
        const active = lang === current;
        return (
          <button
            key={lang}
            type="button"
            lang={lang}
            data-testid={`guest-lang-${lang}`}
            aria-pressed={active}
            aria-label={LANG_NATIVE_NAMES[lang]}
            disabled={pending !== null}
            onClick={() => {
              if (!active) onChange(lang);
            }}
            className={`min-h-11 min-w-11 rounded-full px-3 text-sm font-semibold uppercase transition-colors disabled:opacity-60 ${
              active ? "bg-gray-900 text-white" : "text-gray-700"
            }`}
          >
            {lang}
          </button>
        );
      })}
    </div>
  );
}
