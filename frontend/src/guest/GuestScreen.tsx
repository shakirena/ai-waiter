import { useCallback, useEffect, useState } from "react";

import { enterTable, setGuestLang } from "../api/client";
import type { GuestLang, GuestSessionResponse } from "../api/types";
import { ERROR_MESSAGE, entryErrorKind, isVisitClosed, needsSilentReentry, type GuestErrorKind } from "./errors";
import { browserLang, translate } from "./i18n";
import { readStoredLang, writeStoredLang } from "./langStorage";
import { LanguageSwitcher } from "./LanguageSwitcher";

// Минимальный экран гостя (#84–#86, FR-11 spec #9): вход по токену из адреса, экран стола
// с переключателем языка, экраны ошибок. Полный интерфейс (меню, корзина, чат) — #13.

type ScreenState =
  | { status: "loading"; lang: GuestLang }
  | { status: "ready"; guest: GuestSessionResponse; pendingLang: GuestLang | null; langFailed: boolean }
  | { status: "error"; kind: GuestErrorKind; lang: GuestLang };

function initialLang(): GuestLang {
  return readStoredLang() ?? browserLang();
}

function stateLang(state: ScreenState): GuestLang {
  return state.status === "ready" ? state.guest.lang : state.lang;
}

function ready(guest: GuestSessionResponse): ScreenState {
  return { status: "ready", guest, pendingLang: null, langFailed: false };
}

// Ошибка входа: заведение неизвестно, язык — язык браузера (R-Q2 spec).
function entryError(error: unknown): ScreenState {
  return { status: "error", kind: entryErrorKind(error), lang: browserLang() };
}

interface GuestScreenProps {
  token: string;
}

export function GuestScreen({ token }: GuestScreenProps) {
  const [state, setState] = useState<ScreenState>(() => ({ status: "loading", lang: initialLang() }));
  // Номер попытки входа: «Повторить» и «Начать заново» увеличивают его и перезапускают вход.
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    // Визит открывает только этот запрос из JavaScript, а не загрузка HTML (E-16 spec).
    const controller = new AbortController();
    enterTable(token, readStoredLang(), controller.signal).then(
      (guest) => {
        if (!controller.signal.aborted) setState(ready(guest));
      },
      (error: unknown) => {
        if (!controller.signal.aborted) setState(entryError(error));
      },
    );
    return () => controller.abort();
  }, [token, attempt]);

  const lang = stateLang(state);

  useEffect(() => {
    document.documentElement.lang = lang;
  }, [lang]);

  const restartEntry = useCallback(() => {
    setState((prev) => ({ status: "loading", lang: stateLang(prev) }));
    setAttempt((n) => n + 1);
  }, []);

  const changeLang = useCallback(
    async (next: GuestLang) => {
      if (state.status !== "ready" || state.pendingLang !== null) return;
      const sessionLang = state.guest.lang;
      setState({ ...state, pendingLang: next, langFailed: false });
      const keepLang = () =>
        setState((prev) => (prev.status === "ready" ? { ...prev, pendingLang: null, langFailed: true } : prev));

      let guest: GuestSessionResponse;
      try {
        guest = await setGuestLang(next);
      } catch (error) {
        if (isVisitClosed(error)) {
          // Закрытый визит: новый вход только по кнопке «Начать заново» (ADR-9.2).
          setState({ status: "error", kind: "visit_closed", lang: sessionLang });
          return;
        }
        if (!needsSilentReentry(error)) {
          // Сеть, 5xx, lang_not_supported: язык прежний, без технических подробностей.
          keepLang();
          return;
        }
        // Сессия потеряна (перевыпуск токена, отключение стола, рестарт без секрета) —
        // тихий вход по токену из адреса сразу с новым языком (FR-6 spec).
        try {
          guest = await enterTable(token, next);
        } catch (entryFailure) {
          const kind = entryErrorKind(entryFailure);
          if (kind === "unavailable") keepLang();
          else setState({ status: "error", kind, lang: sessionLang });
          return;
        }
      }
      writeStoredLang(guest.lang);
      setState(ready(guest));
    },
    [state, token],
  );

  return (
    <main
      data-testid="guest-page"
      className="mx-auto flex min-h-dvh w-full max-w-md flex-col gap-6 px-4 py-6 text-gray-900"
    >
      {state.status === "loading" && <LoadingView lang={lang} />}
      {state.status === "error" && <ErrorView kind={state.kind} lang={lang} onRetry={restartEntry} />}
      {state.status === "ready" && (
        <TableView
          guest={state.guest}
          pendingLang={state.pendingLang}
          langFailed={state.langFailed}
          onChangeLang={(next) => void changeLang(next)}
        />
      )}
    </main>
  );
}

function LoadingView({ lang }: { lang: GuestLang }) {
  // Только текст, без скелетонов и анимаций: на слабом интернете экран не мерцает (NFR-2).
  return (
    <div data-testid="guest-loading" role="status" className="flex flex-1 items-center justify-center text-gray-500">
      {translate(lang, "loading")}
    </div>
  );
}

interface TableViewProps {
  guest: GuestSessionResponse;
  pendingLang: GuestLang | null;
  langFailed: boolean;
  onChangeLang: (lang: GuestLang) => void;
}

function TableView({ guest, pendingLang, langFailed, onChangeLang }: TableViewProps) {
  const { tenant, table, lang } = guest;
  return (
    <section data-testid="guest-table-screen" className="flex flex-col gap-6">
      <header className="flex items-start justify-between gap-3">
        {/* Названия заведения и стола — данные кассы/админа: выводятся как текст, не как HTML. */}
        <h1 data-testid="guest-tenant-name" className="min-w-0 text-2xl font-semibold break-words">
          {tenant.name}
        </h1>
        <LanguageSwitcher languages={tenant.languages} current={lang} pending={pendingLang} onChange={onChangeLang} />
      </header>
      {langFailed && (
        <p data-testid="guest-lang-error" role="alert" className="text-sm text-red-700">
          {translate(lang, "langChangeFailed")}
        </p>
      )}
      <div className="rounded-2xl bg-gray-100 px-4 py-5">
        <p className="text-sm text-gray-600">{translate(lang, table.type === "cabin" ? "yourCabin" : "yourTable")}</p>
        <p data-testid="guest-table-name" className="text-xl font-semibold break-words">
          {table.name}
        </p>
      </div>
      <div className="flex flex-col gap-1">
        <p data-testid="guest-welcome" className="text-lg font-medium">
          {translate(lang, "welcome")}
        </p>
        <p className="text-base text-gray-600">{translate(lang, "comingSoon")}</p>
      </div>
    </section>
  );
}

interface ErrorViewProps {
  kind: GuestErrorKind;
  lang: GuestLang;
  onRetry: () => void;
}

function ErrorView({ kind, lang, onRetry }: ErrorViewProps) {
  // «Начать заново» — после закрытия визита: новый вход только по кнопке, без автоповтора (ADR-9.2).
  // «Повторить» — сеть или 5xx (E-15). На остальные ошибки гость идёт к официанту.
  const action =
    kind === "visit_closed"
      ? { testId: "guest-error-restart", label: translate(lang, "restart") }
      : kind === "unavailable"
        ? { testId: "guest-error-retry", label: translate(lang, "retry") }
        : null;

  return (
    <section data-testid="guest-error" role="alert" className="flex flex-1 flex-col items-center justify-center gap-6 text-center">
      <p data-testid="guest-error-message" className="text-xl font-semibold break-words">
        {translate(lang, ERROR_MESSAGE[kind])}
      </p>
      {action && (
        <button
          type="button"
          data-testid={action.testId}
          onClick={onRetry}
          className="min-h-11 w-full rounded-xl bg-gray-900 px-4 py-3 text-base font-semibold text-white"
        >
          {action.label}
        </button>
      )}
    </section>
  );
}
