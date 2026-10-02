import { PlaceholderPage } from "../components/PlaceholderPage";

// Страница для неизвестных маршрутов. Загружается сразу, без отдельного чанка.
export default function NotFoundPage() {
  return (
    <PlaceholderPage
      testId="not-found-page"
      title="Страница не найдена"
      description="Проверьте адрес или отсканируйте QR-код на столе ещё раз."
    />
  );
}
