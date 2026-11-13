import { act, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError, enterTable, setGuestLang } from "../api/client";
import type { ApiErrorCode, GuestEntryResponse, GuestLang, GuestSessionResponse } from "../api/types";
import GuestPage from "../pages/GuestPage";
import { LANG_STORAGE_KEY } from "./langStorage";

// Экран гостя #84–#86: API подменён, ApiError — настоящий (по нему экран выбирает текст).
vi.mock("../api/client", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/client")>();
  return { ...actual, enterTable: vi.fn(), setGuestLang: vi.fn() };
});

const enterTableMock = vi.mocked(enterTable);
const setGuestLangMock = vi.mocked(setGuestLang);

const TOKEN = "Tq3x_9kLmN2pQrStUvWxYz01";

function entry(overrides: Partial<GuestEntryResponse> = {}): GuestEntryResponse {
  return {
    tenant: { name: "Ресторан «Бакы»", languages: ["az", "ru"], default_lang: "az", currency: "AZN" },
    table: { name: "Стол 7", type: "table" },
    visit: { id: "0192-visit", opened_at: "2026-11-04T18:05:00+04:00", is_new: true },
    lang: "ru",
    ...overrides,
  };
}

function session(lang: GuestLang, base: GuestEntryResponse = entry()): GuestSessionResponse {
  const { visit, ...rest } = base;
  return { ...rest, visit: { id: visit.id, opened_at: visit.opened_at }, lang };
}

const apiError = (status: number, code: ApiErrorCode | null) => new ApiError(status, "ошибка", code);

function renderGuest(path = `/t/${TOKEN}`) {
  return render(
    <MemoryRouter initialEntries={[path]}>
      <Routes>
        <Route path="/t/:token/*" element={<GuestPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

function setBrowserLanguage(tag: string) {
  vi.spyOn(window.navigator, "language", "get").mockReturnValue(tag);
}

beforeEach(() => {
  window.localStorage.clear();
  setBrowserLanguage("ru-RU");
});

afterEach(() => {
  vi.restoreAllMocks();
  enterTableMock.mockReset();
  setGuestLangMock.mockReset();
  window.localStorage.clear();
});

describe("#84 экран стола", () => {
  it("входит по токену из адреса и показывает заведение, стол и переключатель", async () => {
    enterTableMock.mockResolvedValueOnce(entry());

    renderGuest();

    expect(await screen.findByTestId("guest-tenant-name")).toHaveTextContent("Ресторан «Бакы»");
    expect(screen.getByTestId("guest-table-name")).toHaveTextContent("Стол 7");
    expect(screen.getByTestId("guest-lang-switch")).toBeInTheDocument();
    expect(screen.getByText("Ваш стол")).toBeInTheDocument();
    expect(enterTableMock).toHaveBeenCalledTimes(1);
    expect(enterTableMock).toHaveBeenCalledWith(TOKEN, null, expect.any(AbortSignal));
  });

  it("токен не выводится на экран", async () => {
    enterTableMock.mockResolvedValueOnce(entry());

    const { container } = renderGuest();

    await screen.findByTestId("guest-table-screen");
    expect(container.innerHTML).not.toContain(TOKEN);
  });

  it("передаёт при входе язык, сохранённый на устройстве", async () => {
    window.localStorage.setItem(LANG_STORAGE_KEY, "az");
    enterTableMock.mockResolvedValueOnce(entry({ lang: "az" }));

    renderGuest();

    await screen.findByTestId("guest-table-screen");
    expect(enterTableMock).toHaveBeenCalledWith(TOKEN, "az", expect.any(AbortSignal));
    expect(screen.getByText("Masanız")).toBeInTheDocument();
  });

  it("пока вход идёт — состояние загрузки на языке устройства", async () => {
    const pending = deferred<GuestEntryResponse>();
    enterTableMock.mockReturnValueOnce(pending.promise);

    renderGuest();

    expect(screen.getByTestId("guest-loading")).toHaveTextContent("Загрузка…");
    await act(async () => pending.resolve(entry()));
    expect(screen.queryByTestId("guest-loading")).not.toBeInTheDocument();
  });

  it("кабина подписана как кабина; язык документа — язык гостя", async () => {
    enterTableMock.mockResolvedValueOnce(entry({ table: { name: "VIP 2", type: "cabin" }, lang: "az" }));

    renderGuest();

    expect(await screen.findByText("Kabinəniz")).toBeInTheDocument();
    expect(document.documentElement.lang).toBe("az");
  });

  it("названия с разметкой выводятся как текст, не как HTML", async () => {
    enterTableMock.mockResolvedValueOnce(
      entry({ tenant: { name: "<b>Кафе</b>", languages: ["ru"], default_lang: "ru", currency: "AZN" } }),
    );

    renderGuest();

    const name = await screen.findByTestId("guest-tenant-name");
    expect(name).toHaveTextContent("<b>Кафе</b>");
    expect(name.querySelector("b")).toBeNull();
  });

  it("размонтирование до ответа отменяет запрос входа", () => {
    enterTableMock.mockReturnValueOnce(new Promise(() => {}));

    const { unmount } = renderGuest();
    const signal = enterTableMock.mock.calls[0]![2]!;
    unmount();

    expect(signal.aborted).toBe(true);
  });
});

describe("#85 экран ошибки", () => {
  it.each([
    ["ru-RU", "QR-код недействителен, обратитесь к официанту"],
    ["az-AZ", "QR-kod etibarsızdır, ofisianta müraciət edin"],
    ["en-US", "QR-kod etibarsızdır, ofisianta müraciət edin"],
  ])("404 qr_invalid, браузер %s → «%s»", async (tag, text) => {
    setBrowserLanguage(tag);
    enterTableMock.mockRejectedValueOnce(apiError(404, "qr_invalid"));

    const { container } = renderGuest();

    expect(await screen.findByTestId("guest-error-message")).toHaveTextContent(text);
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    // Без кода ошибки, токена и технических подробностей.
    expect(container.textContent).not.toMatch(/qr_invalid|404|ApiError/);
    expect(container.innerHTML).not.toContain(TOKEN);
  });

  it("язык ошибки — браузера, даже если на устройстве выбран другой (R-Q2)", async () => {
    window.localStorage.setItem(LANG_STORAGE_KEY, "az");
    enterTableMock.mockRejectedValueOnce(apiError(404, "qr_invalid"));

    renderGuest();

    expect(await screen.findByTestId("guest-error-message")).toHaveTextContent("QR-код недействителен");
  });

  it("422 валидации токена → как недействительный QR", async () => {
    enterTableMock.mockRejectedValueOnce(apiError(422, null));

    renderGuest(`/t/${"x".repeat(200)}`);

    expect(await screen.findByTestId("guest-error-message")).toHaveTextContent("QR-код недействителен");
  });

  it("403 table_inactive", async () => {
    enterTableMock.mockRejectedValueOnce(apiError(403, "table_inactive"));

    renderGuest();

    expect(await screen.findByTestId("guest-error-message")).toHaveTextContent(
      "Стол временно не обслуживается, обратитесь к официанту",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("429 rate_limited без кнопки и без автоповтора", async () => {
    enterTableMock.mockRejectedValueOnce(apiError(429, "rate_limited"));

    renderGuest();

    expect(await screen.findByTestId("guest-error-message")).toHaveTextContent(
      "Слишком много попыток, повторите через минуту",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
    expect(enterTableMock).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["503 try_again", apiError(503, "try_again")],
    ["500", apiError(500, null)],
    ["сеть", new TypeError("Failed to fetch")],
  ])("%s → «Сервис временно недоступен», «Повторить» входит заново", async (_name, error) => {
    enterTableMock.mockRejectedValueOnce(error).mockResolvedValueOnce(entry());

    renderGuest();

    expect(await screen.findByTestId("guest-error-message")).toHaveTextContent("Сервис временно недоступен");
    expect(enterTableMock).toHaveBeenCalledTimes(1);

    fireEvent.click(screen.getByTestId("guest-error-retry"));

    expect(await screen.findByTestId("guest-table-screen")).toBeInTheDocument();
    expect(enterTableMock).toHaveBeenCalledTimes(2);
    expect(enterTableMock).toHaveBeenLastCalledWith(TOKEN, null, expect.any(AbortSignal));
  });

  it("кнопка «Повторить» на языке браузера (az)", async () => {
    setBrowserLanguage("az");
    enterTableMock.mockRejectedValueOnce(new TypeError("Failed to fetch"));

    renderGuest();

    expect(await screen.findByTestId("guest-error-retry")).toHaveTextContent("Yenidən cəhd et");
    expect(screen.getByTestId("guest-error-message")).toHaveTextContent("Xidmət müvəqqəti olaraq əlçatan deyil");
  });
});

describe("#86 переключатель языка", () => {
  it("меняет тексты сразу, вызывает API и сохраняет выбор на устройстве", async () => {
    enterTableMock.mockResolvedValueOnce(entry({ lang: "ru" }));
    const pending = deferred<GuestSessionResponse>();
    setGuestLangMock.mockReturnValueOnce(pending.promise);

    renderGuest();
    await screen.findByText("Ваш стол");
    expect(screen.getByTestId("guest-lang-ru")).toHaveAttribute("aria-pressed", "true");

    fireEvent.click(screen.getByTestId("guest-lang-az"));

    expect(setGuestLangMock).toHaveBeenCalledWith("az");
    // Пока запрос идёт — кнопки неактивны, повторного запроса нет.
    expect(screen.getByTestId("guest-lang-az")).toBeDisabled();
    fireEvent.click(screen.getByTestId("guest-lang-az"));
    expect(setGuestLangMock).toHaveBeenCalledTimes(1);

    await act(async () => pending.resolve(session("az")));

    expect(screen.getByText("Masanız")).toBeInTheDocument();
    expect(screen.getByText("Xoş gəlmisiniz!")).toBeInTheDocument();
    expect(screen.getByTestId("guest-lang-az")).toHaveAttribute("aria-pressed", "true");
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBe("az");
    expect(document.documentElement.lang).toBe("az");
    expect(enterTableMock).toHaveBeenCalledTimes(1);
  });

  it("выбор остаётся после перезагрузки: следующий вход передаёт его серверу", async () => {
    enterTableMock.mockResolvedValueOnce(entry({ lang: "ru" }));
    setGuestLangMock.mockResolvedValueOnce(session("az"));

    const first = renderGuest();
    fireEvent.click(await screen.findByTestId("guest-lang-az"));
    await screen.findByText("Masanız");
    first.unmount();

    enterTableMock.mockResolvedValueOnce(entry({ lang: "az" }));
    renderGuest();

    await screen.findByText("Masanız");
    expect(enterTableMock).toHaveBeenLastCalledWith(TOKEN, "az", expect.any(AbortSignal));
  });

  it("нажатие на текущий язык ничего не делает", async () => {
    enterTableMock.mockResolvedValueOnce(entry({ lang: "ru" }));

    renderGuest();
    fireEvent.click(await screen.findByTestId("guest-lang-ru"));

    expect(setGuestLangMock).not.toHaveBeenCalled();
  });

  it("заведение с одним языком — переключатель не показывается (E-13)", async () => {
    enterTableMock.mockResolvedValueOnce(
      entry({ tenant: { name: "Кафе", languages: ["ru"], default_lang: "ru", currency: "AZN" }, lang: "ru" }),
    );

    renderGuest();

    await screen.findByTestId("guest-table-screen");
    expect(screen.queryByTestId("guest-lang-switch")).not.toBeInTheDocument();
  });

  it("показывает только языки заведения в его порядке", async () => {
    enterTableMock.mockResolvedValueOnce(
      entry({ tenant: { name: "Кафе", languages: ["ru", "az"], default_lang: "ru", currency: "AZN" } }),
    );

    renderGuest();

    const buttons = (await screen.findByTestId("guest-lang-switch")).querySelectorAll("button");
    expect([...buttons].map((b) => b.dataset.testid)).toEqual(["guest-lang-ru", "guest-lang-az"]);
  });

  it.each([
    ["сеть", new TypeError("Failed to fetch")],
    ["503", apiError(503, "try_again")],
    ["422 lang_not_supported", apiError(422, "lang_not_supported")],
    ["422 без кода", apiError(422, null)],
  ])("ошибка %s — язык прежний, понятное сообщение без подробностей", async (_name, error) => {
    enterTableMock.mockResolvedValueOnce(entry({ lang: "ru" }));
    setGuestLangMock.mockRejectedValueOnce(error);

    const { container } = renderGuest();
    fireEvent.click(await screen.findByTestId("guest-lang-az"));

    expect(await screen.findByTestId("guest-lang-error")).toHaveTextContent("Не удалось сменить язык");
    expect(screen.getByText("Ваш стол")).toBeInTheDocument();
    expect(screen.getByTestId("guest-lang-ru")).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByTestId("guest-lang-az")).toBeEnabled();
    expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBeNull();
    expect(container.textContent).not.toMatch(/422|503|lang_not_supported|Failed/);
    expect(enterTableMock).toHaveBeenCalledTimes(1);
  });

  it("после ошибки повторное нажатие снимает сообщение и меняет язык", async () => {
    enterTableMock.mockResolvedValueOnce(entry({ lang: "ru" }));
    setGuestLangMock.mockRejectedValueOnce(new TypeError("Failed to fetch")).mockResolvedValueOnce(session("az"));

    renderGuest();
    fireEvent.click(await screen.findByTestId("guest-lang-az"));
    await screen.findByTestId("guest-lang-error");
    fireEvent.click(screen.getByTestId("guest-lang-az"));

    expect(await screen.findByText("Masanız")).toBeInTheDocument();
    expect(screen.queryByTestId("guest-lang-error")).not.toBeInTheDocument();
  });

  it.each(["guest_session_required", "guest_session_invalid"] as const)(
    "401 %s — тихий повторный вход по токену с новым языком",
    async (code) => {
      enterTableMock.mockResolvedValueOnce(entry({ lang: "ru" })).mockResolvedValueOnce(entry({ lang: "az" }));
      setGuestLangMock.mockRejectedValueOnce(apiError(401, code));

      renderGuest();
      fireEvent.click(await screen.findByTestId("guest-lang-az"));

      expect(await screen.findByText("Masanız")).toBeInTheDocument();
      expect(enterTableMock).toHaveBeenCalledTimes(2);
      expect(enterTableMock).toHaveBeenLastCalledWith(TOKEN, "az");
      expect(window.localStorage.getItem(LANG_STORAGE_KEY)).toBe("az");
    },
  );

  it("тихий повторный вход отклонён (стол отключён) — экран ошибки", async () => {
    enterTableMock.mockResolvedValueOnce(entry({ lang: "ru" })).mockRejectedValueOnce(apiError(403, "table_inactive"));
    setGuestLangMock.mockRejectedValueOnce(apiError(401, "guest_session_invalid"));

    renderGuest();
    fireEvent.click(await screen.findByTestId("guest-lang-az"));

    expect(await screen.findByTestId("guest-error-message")).toHaveTextContent("Стол временно не обслуживается");
  });

  it("тихий повторный вход без сети — язык прежний, сообщение об ошибке", async () => {
    enterTableMock.mockResolvedValueOnce(entry({ lang: "ru" })).mockRejectedValueOnce(new TypeError("Failed"));
    setGuestLangMock.mockRejectedValueOnce(apiError(401, "guest_session_required"));

    renderGuest();
    fireEvent.click(await screen.findByTestId("guest-lang-az"));

    expect(await screen.findByTestId("guest-lang-error")).toBeInTheDocument();
    expect(screen.getByText("Ваш стол")).toBeInTheDocument();
  });

  it("401 visit_closed — «Визит завершён», новый вход только по кнопке «Начать заново»", async () => {
    enterTableMock.mockResolvedValueOnce(entry({ lang: "ru" }));
    setGuestLangMock.mockRejectedValueOnce(apiError(401, "visit_closed"));

    renderGuest();
    fireEvent.click(await screen.findByTestId("guest-lang-az"));

    expect(await screen.findByTestId("guest-error-message")).toHaveTextContent("Визит завершён");
    const restart = screen.getByTestId("guest-error-restart");
    expect(restart).toHaveTextContent("Начать заново");
    // Без автоповтора: вход был только один.
    await new Promise((r) => setTimeout(r, 20));
    expect(enterTableMock).toHaveBeenCalledTimes(1);

    enterTableMock.mockResolvedValueOnce(
      entry({ lang: "ru", visit: { id: "0193-new", opened_at: "2026-11-04T20:00:00+04:00", is_new: true } }),
    );
    fireEvent.click(restart);

    expect(await screen.findByTestId("guest-table-screen")).toBeInTheDocument();
    expect(enterTableMock).toHaveBeenCalledTimes(2);
  });
});
